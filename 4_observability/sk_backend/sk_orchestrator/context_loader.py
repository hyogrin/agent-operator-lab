"""XML context file loader for product and recommendation data."""

import xml.etree.ElementTree as ET


def load_xml_context(xml_path: str) -> str:
    """
    Load an XML context file and return its content as a string.

    The raw XML is returned so the LLM can parse structured product
    information such as ingredients, usage instructions, and ratings.

    Parameters:
    xml_path (str): Absolute or relative path to the XML file.

    Returns:
    str: XML content as a unicode string.

    Raises:
    FileNotFoundError: If the XML file does not exist.
    ET.ParseError: If the file contains invalid XML.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    return ET.tostring(root, encoding="unicode")
