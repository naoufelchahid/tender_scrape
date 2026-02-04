"""
Pipeline Stage: Classification Container
Hierarchy restructuring - restructures markdown headers based on document type
"""

import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def extract_yaml_header(content: str) -> Tuple[str, str]:
    """
    Extract YAML frontmatter header from content if present.
    
    Args:
        content: Document content
        
    Returns:
        Tuple of (yaml_header, remaining_content)
    """
    lines = content.split('\n')
    
    # Check if content starts with YAML frontmatter (---)
    if not lines or not lines[0].strip() == '---':
        return "", content
    
    # Find the closing ---
    yaml_end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            yaml_end = i
            break
    
    if yaml_end == -1:
        # No closing ---, not valid YAML
        return "", content
    
    # Extract YAML header and remaining content
    yaml_header = '\n'.join(lines[:yaml_end + 1])
    remaining_content = '\n'.join(lines[yaml_end + 1:])
    
    return yaml_header, remaining_content


def remove_all_markers(content: str) -> str:
    """
    Remove all markdown headers from content.
    Used for avis and form documents.
    Preserves YAML frontmatter.
    
    Args:
        content: Document content
        
    Returns:
        Content with all markdown headers removed
    """
    # Extract and preserve YAML header
    yaml_header, body = extract_yaml_header(content)
    
    # Remove all markdown headers (# through ######)
    lines = body.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Check if line starts with markdown header
        if re.match(r'^#{1,6}\s+', line):
            # Remove the markers but keep the text
            cleaned_line = re.sub(r'^#{1,6}\s+', '', line)
            cleaned_lines.append(cleaned_line)
        else:
            cleaned_lines.append(line)
    
    # Combine YAML header with cleaned content
    cleaned_body = '\n'.join(cleaned_lines)
    if yaml_header:
        return yaml_header + '\n' + cleaned_body
    return cleaned_body


def remove_page_markers(content: str) -> str:
    """
    Remove OCR-generated page markers (e.g., "## Page 1", "## Page 21").
    
    Args:
        content: Document content
        
    Returns:
        Content with page markers removed
    """
    lines = content.split('\n')
    cleaned_lines = []
    
    # Pattern to match page markers: ## Page X (with optional spaces)
    page_marker_pattern = re.compile(r'^##\s+[Pp]age\s+\d+\s*$')
    
    for line in lines:
        # Skip lines that match page marker pattern
        if page_marker_pattern.match(line.strip()):
            logger.debug(f"Removing page marker: {line.strip()}")
            continue
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


def restructure_strict_hierarchy(content: str) -> str:
    """
    Restructure documents with strict hierarchy:
    - Piece → H1 (#)
    - Chapitre/Section → H2 (##)
    - Article/Annexe → H3 (###)
    
    Ensures no headers exist between H3 markers to preserve hierarchy.
    Preserves YAML frontmatter.
    
    Args:
        content: Document content
        
    Returns:
        Content with restructured hierarchy
    """
    # Extract and preserve YAML header
    yaml_header, body = extract_yaml_header(content)
    
    lines = body.split('\n')
    restructured_lines = []
    
    # Patterns for detection (case-insensitive, French/Arabic)
    piece_pattern = re.compile(
        r'^\s*(?:piece|pièce|piéce|القسم)\s*[:\-]?\s*(\d+|[IVX]+|[A-Z])?',
        re.IGNORECASE
    )
    
    chapitre_section_pattern = re.compile(
        r'^\s*(?:chapitre|section|الفصل)\s*[:\-]?\s*(\d+|[IVX]+|[A-Z])?',
        re.IGNORECASE
    )
    
    article_annexe_pattern = re.compile(
        r'^\s*(?:article|art\.|annexe|المادة|الملحق)\s*[:\-]?\s*(\d+|[IVX]+|[A-Z])?\s*[:\-]?',
        re.IGNORECASE
    )
    
    # SOMMAIRE / TOC Detection
    sommaire_start_pattern = re.compile(r'^\s*(?:sommaire|table\s+des\s+mati[èe]res)', re.IGNORECASE)
    
    # State flags
    in_sommaire = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            if not in_sommaire:
                restructured_lines.append(line)
            continue
        
        # Check start of sommaire
        if not in_sommaire and sommaire_start_pattern.match(stripped):
            logger.info(f"Detected start of SOMMAIRE at line {i}")
            in_sommaire = True
            restructured_lines.append("<!-- SOMMAIRE REMOVED -->")
            continue
            
        # First, remove any existing markdown headers
        cleaned_line = re.sub(r'^#{1,6}\s+', '', line)
        cleaned_stripped = cleaned_line.strip()
        
        # Check for strict hierarchy headers
        is_header = False
        new_header_line = cleaned_line
        
        if piece_pattern.match(cleaned_stripped):
            new_header_line = f"# {cleaned_stripped}"
            is_header = True
        elif chapitre_section_pattern.match(cleaned_stripped):
            new_header_line = f"## {cleaned_stripped}"
            is_header = True
        elif article_annexe_pattern.match(cleaned_stripped):
            new_header_line = f"### {cleaned_stripped}"
            is_header = True
            
        if in_sommaire:
            # Logic to exit sommaire:
            # If we hit a duplicate header that matches what we've seen? 
            # Or if we hit "content" -> heuristic: a line that is NOT a header and NOT a page number
            
            # Simple heuristic: If we hit a header, we are still likely in sommaire unless it looks like a real start?
            # Actually, Sommaire is composed OF headers.
            # We exit when we hit something that is NOT a header and NOT a page number artifacts ( ... 12)
            
            # Check for page number pattern at end of line (common in TOC)
            # e.g. "...... 12", "  4"
            has_page_num = re.search(r'[\.\s]+\d+$', cleaned_stripped)
            
            if is_header or has_page_num:
                # Still in sommaire structure, ignore this line
                continue
            else:
                # We hit normal text. The Sommaire is likely over.
                # However, this line itself might be the restart of the body.
                # Or it could be a false positive. 
                # Let's assume if it's not a header and not a page number, we are back to body.
                logger.info(f"End of SOMMAIRE detected at line {i} (encountered content: {cleaned_stripped[:20]}...)")
                in_sommaire = False
                
                # Fallthrough to process this line as normal body content
                pass

        # Normal processing (or just exited sommaire)
        if is_header:
            restructured_lines.append(new_header_line)
            if is_header:
                 # Start of a "Piece" or "Chapitre" often signals end of Sommaire if we missed it
                 # If we were in Sommaire and saw a "Piece", we ignored it above.
                 # Wait.. the logic above says `if is_header... continue` when in_sommaire.
                 # This assumes the TOC *mimics* the structure.
                 # But we need a robust way to know when the TOC *ends* and the *real* header begins.
                 # Often TOC ends with "Chapitre X... 45" or just "Chapitre X"
                 # And the Real section starts with "Chapitre X" followed by text.
                 pass
        else:
             restructured_lines.append(cleaned_line)

    # Combine YAML header with restructured content
    restructured_body = '\n'.join(restructured_lines)
    if yaml_header:
        return yaml_header + '\n' + restructured_body
    return restructured_body


def restructure_document(content: str, doc_type: str) -> str:
    """
    Restructure document hierarchy based on document type.
    
    Args:
        content: Document content
        doc_type: Document type (avis, form, administrative, specification, product, etc.)
        
    Returns:
        Restructured content
    """
    doc_type_lower = doc_type.lower()
    
    # Avis and Form: remove all markers
    if doc_type_lower in ['avis', 'form']:
        logger.info(f"Removing all markers from {doc_type} document")
        return remove_all_markers(content)
    
    # Administrative: apply full hierarchy restructuring
    elif doc_type_lower == 'administrative':
        logger.info(f"Restructuring hierarchy for administrative document")
        return restructure_strict_hierarchy(content)
    
    # Specification: apply full hierarchy restructuring (same as administrative)
    elif doc_type_lower == 'specification':
        logger.info(f"Restructuring hierarchy for specification document (strict mode)")
        return restructure_strict_hierarchy(content)
    
    # Product: keep as-is (BDP extractor handles these)
    elif doc_type_lower == 'product':
        logger.info(f"Keeping existing structure for {doc_type} document")
        return content
    
    # Unknown or other types: keep as-is
    else:
        logger.info(f"No restructuring applied for document type: {doc_type}")
        return content


def apply_article_detection(content: str) -> str:
    """
    Apply only Article/Annexe detection to content (for specification documents).
    Preserves YAML frontmatter and existing structure.
    
    Args:
        content: Document content
        
    Returns:
        Content with Article/Annexe headers converted to H3
    """
    # Extract and preserve YAML header
    yaml_header, body = extract_yaml_header(content)
    
    lines = body.split('\n')
    restructured_lines = []
    
    # Pattern for Article/Annexe detection
    article_annexe_pattern = re.compile(
        r'^\s*(?:article|art\.|annexe|المادة|الملحق)\s*[:\-]?\s*(\d+|[IVX]+|[A-Z])?\s*[:\-]?',
        re.IGNORECASE
    )
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            restructured_lines.append(line)
            continue
        
        # Check if line is already a markdown header
        is_existing_header = re.match(r'^#{1,6}\s+', line)
        
        # Check for Article/Annexe
        if article_annexe_pattern.match(stripped):
            # Remove any existing markdown headers first
            cleaned_line = re.sub(r'^#{1,6}\s+', '', line).strip()
            restructured_lines.append(f"### {cleaned_line}")
            logger.debug(f"Detected Article/Annexe (H3): {cleaned_line}")
            continue
        
        # Keep line as-is (including existing headers)
        restructured_lines.append(line)
    
    # Combine YAML header with restructured content
    restructured_body = '\n'.join(restructured_lines)
    if yaml_header:
        return yaml_header + '\n' + restructured_body
    return restructured_body


def restructure_by_type(markdown_text: str) -> str:
    """
    Process markdown text and restructure each document block based on its type.
    
    Expected format:
        # File: filename.pdf
        > Document Type: administrative
        ... content ...
        ---
        # File: another.docx
        > Document Type: avis
        ... content ...
    
    Args:
        markdown_text: Full markdown content with multiple documents
        
    Returns:
        Restructured markdown text
    """
    if not markdown_text:
        return ""
    
    lines = markdown_text.split('\n')
    
    # Find document boundaries
    doc_starts = []
    for i, line in enumerate(lines):
        if line.startswith("# File:"):
            doc_starts.append(i)
    
    # Add end marker
    doc_starts.append(len(lines))
    
    # Process each document block
    result_parts = []
    
    for k in range(len(doc_starts) - 1):
        block_start = doc_starts[k]
        block_end = doc_starts[k + 1]
        
        # Extract document type and content boundaries
        doc_type = None
        content_start = block_start + 1
        
        # Search for Document Type header (should be within first ~10 lines)
        for i in range(block_start, min(block_start + 10, block_end)):
            line = lines[i].strip()
            if line.lower().startswith("> document type:"):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    doc_type = parts[1].strip().lower()
                content_start = i + 1
                break
        
        # Extract header and content separately
        header_lines = lines[block_start:content_start]
        content_lines = lines[content_start:block_end]
        
        # Reconstruct content
        content = '\n'.join(content_lines)
        
        # Remove page markers first (applies to all document types)
        content = remove_page_markers(content)
        
        # Restructure based on type
        if doc_type:
            restructured_content = restructure_document(content, doc_type)
        else:
            logger.warning(f"No document type found for block starting at line {block_start}")
            restructured_content = content
        
        # Combine header + restructured content
        result_parts.append('\n'.join(header_lines))
        result_parts.append(restructured_content)
    
    return '\n'.join(result_parts)
