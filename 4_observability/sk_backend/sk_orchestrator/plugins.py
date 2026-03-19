"""Semantic Kernel plugins that serve XML-grounded context."""

from semantic_kernel.functions import kernel_function


class ProductPlugin:
    """
    SK Plugin wrapping productAgent.

    Reads product detail from product_contexts.xml and returns it
    as context for LLM-based answer generation.
    """

    def __init__(self, context_loader, xml_path: str, tracer):
        """
        Initialise the plugin with a context loader.

        Parameters:
        context_loader: Callable(str) -> str that loads XML.
        xml_path (str): Path to product_contexts.xml.
        tracer: OpenTelemetry tracer instance.
        """
        self._load = context_loader
        self._path = xml_path
        self._tracer = tracer

    @kernel_function(
        name="search_products",
        description=(
            "Search for detailed product information by query"
        ),
    )
    def search_products(self, query: str) -> str:
        """
        Retrieve product detail context from XML.

        Parameters:
        query (str): User's product-related question.

        Returns:
        str: XML-formatted product specification.
        """
        with self._tracer.start_as_current_span(
            "productAgent.search_products"
        ) as span:
            span.set_attribute("agent.name", "productAgent")
            span.set_attribute("agent.method", "search_products")
            span.set_attribute("agent.query", query)
            ctx = self._load(self._path)
            span.set_attribute("context.source", self._path)
            span.set_attribute("context.length", len(ctx))
            return ctx


class RecommendationPlugin:
    """
    SK Plugin wrapping recommendAgent.

    Reads 3 recommended products from recommendation_contexts.xml
    and returns them as context for LLM-based recommendation.
    """

    def __init__(self, context_loader, xml_path: str, tracer):
        """
        Initialise the plugin with a context loader.

        Parameters:
        context_loader: Callable(str) -> str that loads XML.
        xml_path (str): Path to recommendation_contexts.xml.
        tracer: OpenTelemetry tracer instance.
        """
        self._load = context_loader
        self._path = xml_path
        self._tracer = tracer

    @kernel_function(
        name="search_recommendations",
        description=(
            "Search for personalized product recommendations"
        ),
    )
    def search_recommendations(self, query: str) -> str:
        """
        Retrieve recommendation context from XML.

        Parameters:
        query (str): User's recommendation-related question.

        Returns:
        str: XML-formatted info for 3 recommended products.
        """
        with self._tracer.start_as_current_span(
            "recommendAgent.search_recsys"
        ) as span:
            span.set_attribute("agent.name", "recommendAgent")
            span.set_attribute("agent.method", "search_recsys")
            span.set_attribute("agent.query", query)
            ctx = self._load(self._path)
            span.set_attribute("context.source", self._path)
            span.set_attribute("context.length", len(ctx))
            return ctx
