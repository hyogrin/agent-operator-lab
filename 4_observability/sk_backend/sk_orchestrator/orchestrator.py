"""Core SK Orchestrator — intent classification and LLM answer."""

import json
import os
from typing import Any, Dict, Optional, Tuple

import semantic_kernel as sk
from opentelemetry import trace
from semantic_kernel.connectors.ai.open_ai import (
    AzureChatCompletion,
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.contents import ChatHistory

from sk_orchestrator.config import Settings
from sk_orchestrator.context_loader import load_xml_context
from sk_orchestrator.models import (
    INTENT_AGENT_MAP,
    IntentResult,
    IntentType,
)
from sk_orchestrator.plugins import (
    ProductPlugin,
    RecommendationPlugin,
)


class SKOrchestrator:
    """
    High-level orchestrator that wires Semantic Kernel components.

    Usage (as a module)::

        from sk_orchestrator import SKOrchestrator, Settings

        settings = Settings()          # reads .env
        orch = SKOrchestrator(settings)
        result = await orch.run("화장품 추천해줘")

    Parameters:
    settings (Settings): Application configuration.
    tracer: Optional OpenTelemetry tracer override.
    """

    def __init__(
        self,
        settings: Settings,
        tracer: Optional[trace.Tracer] = None,
    ) -> None:
        """
        Build kernel, register plugins, and configure telemetry.

        Parameters:
        settings (Settings): Validated application settings.
        tracer: Optional pre-existing OTel tracer.
        """
        self._settings = settings
        self._tracer = tracer or trace.get_tracer(
            settings.service_name, "1.0.0"
        )

        # Enable SK OTEL diagnostics
        os.environ[
            "SEMANTICKERNEL_EXPERIMENTAL_GENAI_ENABLE_"
            "OTEL_DIAGNOSTICS"
        ] = "true"

        # Build kernel
        self._kernel = sk.Kernel()

        # Strip trailing path segments (e.g. /openai/v1) that some
        # .env files include — SK expects the base URL only.
        endpoint = settings.azure_openai_endpoint.rstrip("/")
        for suffix in ["/openai/v1", "/openai"]:
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)]
                break

        if settings.aoai_auth_method == "credential":
            from azure.identity import (
                DefaultAzureCredential,
            )

            chat_svc = AzureChatCompletion(
                deployment_name=(
                    settings
                    .azure_openai_chat_deployment_name
                ),
                endpoint=endpoint,
                credential=DefaultAzureCredential(),
                api_version=(
                    settings.azure_openai_api_version
                ),
            )
        else:
            chat_svc = AzureChatCompletion(
                deployment_name=(
                    settings
                    .azure_openai_chat_deployment_name
                ),
                endpoint=endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=(
                    settings.azure_openai_api_version
                ),
            )
        self._kernel.add_service(chat_svc)

        # Register plugins
        self._kernel.add_plugin(
            ProductPlugin(
                load_xml_context,
                settings.product_contexts_path,
                self._tracer,
            ),
            plugin_name="ProductPlugin",
        )
        self._kernel.add_plugin(
            RecommendationPlugin(
                load_xml_context,
                settings.recommendation_contexts_path,
                self._tracer,
            ),
            plugin_name="RecommendationPlugin",
        )

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    async def run(self, query: str) -> Dict[str, Any]:
        """
        Execute the full pipeline: classify → select context → answer.

        Parameters:
        query (str): User query text.

        Returns:
        Dict[str, Any]: Pipeline result with keys ``query``,
            ``intent``, ``confidence``, ``agent``, ``method``,
            ``context_source``, ``answer``.
        """
        with self._tracer.start_as_current_span(
            "evaluation_pipeline"
        ) as span:
            span.set_attribute("user.query", query)

            intent = await self.classify_intent(query)
            answer, context_source = await self.route_and_execute(
                query, intent
            )

            mapping = INTENT_AGENT_MAP.get(
                intent.intent.value, {}
            )
            result = {
                "query": query,
                "intent": intent.intent.value,
                "confidence": intent.confidence,
                "agent": mapping.get("agent", "unknown"),
                "method": mapping.get("method", "unknown"),
                "context_source": context_source,
                "answer": answer,
            }
            span.set_attribute(
                "pipeline.intent", intent.intent.value
            )
            return result

    async def classify_intent(self, query: str) -> IntentResult:
        """
        Classify user intent via structured JSON output.

        Parameters:
        query (str): User query text.

        Returns:
        IntentResult: Classified intent with confidence.
        """
        with self._tracer.start_as_current_span(
            "intent_classification"
        ) as span:
            span.set_attribute("user.query", query)

            chat = ChatHistory()
            chat.add_system_message(
                "You are an intent classifier for a beauty/"
                "cosmetics chat app. "
                "Classify the user query into one of these "
                "intents:\n"
                "- product_search: questions about specific "
                "products\n"
                "- recommendation: requests for product "
                "recommendations\n"
                "- policy: questions about policies (return, "
                "shipping, etc.)\n"
                "- beauty: general beauty tips and advice\n"
                "- unknown: cannot classify\n\n"
                "Respond ONLY with valid JSON matching this "
                "schema:\n"
                '{"intent": "<type>", "confidence": <0-1>, '
                '"reasoning": "<why>"}'
            )
            chat.add_user_message(query)

            settings = AzureChatPromptExecutionSettings(
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            chat_svc = self._kernel.get_service(
                type=AzureChatCompletion
            )
            responses = await chat_svc.get_chat_message_contents(
                chat_history=chat,
                settings=settings,
                kernel=self._kernel,
            )
            response_text = str(responses[0])

            try:
                result_dict = json.loads(response_text)
                intent_result = IntentResult(**result_dict)
            except (json.JSONDecodeError, Exception):
                intent_result = IntentResult(
                    intent=IntentType.UNKNOWN,
                    confidence=0.0,
                    reasoning="Failed to parse intent",
                )

            span.set_attribute(
                "intent.type", intent_result.intent.value
            )
            span.set_attribute(
                "intent.confidence", intent_result.confidence
            )
            return intent_result

    async def route_and_execute(
        self,
        query: str,
        intent: IntentResult,
    ) -> Tuple[str, str]:
        """
        Select XML context based on intent and generate answer.

        Parameters:
        query (str): Original user query.
        intent (IntentResult): Classified intent.

        Returns:
        Tuple[str, str]: (llm_answer, context_source_path).
        """
        with self._tracer.start_as_current_span(
            "agent_routing"
        ) as span:
            span.set_attribute(
                "intent.type", intent.intent.value
            )

            xml_ctx, agent_span, sys_prompt, src = (
                self._select_xml_context(intent)
            )
            span.set_attribute("agent.span_name", agent_span)
            span.set_attribute("context.length", len(xml_ctx))

            with self._tracer.start_as_current_span(
                agent_span
            ) as a_span:
                a_span.set_attribute("agent.query", query)
                a_span.set_attribute("context.source", src)

                chat = ChatHistory()
                chat.add_system_message(sys_prompt)
                chat.add_user_message(query)

                settings = AzureChatPromptExecutionSettings(
                    temperature=0.1,
                )

                chat_svc = self._kernel.get_service(
                    type=AzureChatCompletion
                )
                responses = (
                    await chat_svc.get_chat_message_contents(
                        chat_history=chat,
                        settings=settings,
                        kernel=self._kernel,
                    )
                )
                answer = str(responses[0])
                a_span.set_attribute(
                    "response.length", len(answer)
                )
                return answer, src

    def select_xml_context(
        self,
        intent: IntentResult,
    ) -> Tuple[str, str, str, str]:
        """
        Public wrapper for XML context selection.

        Useful when the notebook needs to call the selector
        directly for evaluation dataset construction.

        Parameters:
        intent (IntentResult): Classified intent.

        Returns:
        Tuple[str, str, str, str]:
            (xml_context, agent_span_name, system_prompt,
             context_source).
        """
        return self._select_xml_context(intent)

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    def _select_xml_context(
        self,
        intent: IntentResult,
    ) -> Tuple[str, str, str, str]:
        """
        Map classified intent to XML context and system prompt.

        Parameters:
        intent (IntentResult): Classified intent.

        Returns:
        Tuple containing xml_context, agent_span_name,
            system_prompt, and context_source path.
        """
        s = self._settings
        if intent.intent.value == IntentType.PRODUCT_SEARCH.value:
            xml_ctx = load_xml_context(s.product_contexts_path)
            agent_span = "productAgent.search_products"
            src = s.product_contexts_path
            sys_prompt = (
                "You are a beauty product expert assistant "
                "for a Korean cosmetics brand.\n"
                "The following XML contains detailed "
                "specification of a specific product.\n"
                "Use this product information to answer the "
                "user's question accurately and helpfully "
                "in Korean.\n\n"
                "<product_context>\n"
                + xml_ctx
                + "\n</product_context>"
            )
        elif (
            intent.intent.value
            == IntentType.RECOMMENDATION.value
        ):
            xml_ctx = load_xml_context(
                s.recommendation_contexts_path
            )
            agent_span = "recommendAgent.search_recsys"
            src = s.recommendation_contexts_path
            sys_prompt = (
                "You are a beauty product recommendation "
                "assistant for a Korean cosmetics brand.\n"
                "The following XML contains information about "
                "3 recommended products.\n"
                "Based on the user's skin concern or request, "
                "recommend the most suitable products from "
                "this list, briefly explaining why each is "
                "recommended. Respond in Korean.\n\n"
                "<recommendation_context>\n"
                + xml_ctx
                + "\n</recommendation_context>"
            )
        else:
            xml_ctx = ""
            agent_span = "defaultAgent"
            src = "none"
            sys_prompt = (
                "You are a helpful beauty and cosmetics "
                "assistant. Answer the user's question "
                "in Korean."
            )

        return xml_ctx, agent_span, sys_prompt, src
