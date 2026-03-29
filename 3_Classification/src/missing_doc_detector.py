"""
Pipeline Stage: Classification Container
Missing document detector - searches markdown for missing document types and marks them
"""

import re
import logging
from typing import List, Tuple, Set

# Import LogicalDocument for creating extracted documents
from .document_splitter import LogicalDocument
from .bdp_extractor import identify_and_tag_french_boq

logger = logging.getLogger(__name__)


def detect_missing_documents(markdown_text: str, found_types: Set[str]) -> Tuple[str, Set[str]]:
    """
    Detect and mark missing document types in markdown content.
    
    Searches the ENTIRE markdown content (including within already classified documents)
    for missing document types and marks them with HTML comment balises.
    
    Args:
        markdown_text: Full markdown content
        found_types: Set of document types already found during classification
        
    Returns:
        Tuple of (modified_markdown, newly_found_types)
    """
    newly_found_types = set()
    modified_markdown = markdown_text
    
    # Define detection order and functions
    # Order: 
    # 1. product (bdp) - prioritized
    # 2. avis_fr
    # 3. avis_ar
    # 4. acte_engagement
    # 5. declaration
    
    # detection_steps list: (doc_type, detection_function)
    # If detection_function is None, it implies special handling inside the loop
    detection_steps = [
        ('product', None),  # Special handling via bdp_extractor
        ('avis_fr', detect_avis_fr),
        ('avis_ar', detect_avis_ar),
        ('acte_engagement', detect_acte_engagement),
        ('declaration', detect_declaration),
    ]
    
    for doc_type, detect_func in detection_steps:
        # Skip if already found (unless we want to force re-detection, but usually we don't)
        if doc_type in found_types:
            continue
            
        logger.info(f"Searching for missing document type: {doc_type}")
        
        detections = []
        if doc_type == 'product':
            # Use the imported BDP extractor logic
            # This function returns modified markdown with BDP tags if found
            # We need to check if tags were added to determine if we "found" it
            
            # Check if tags exist BEFORE (unlikely if in missing detection, but per logic)
            had_bdp = '<!-- BDP_START -->' in modified_markdown
            
            # Run extraction/tagging
            modified_markdown = identify_and_tag_french_boq(modified_markdown)
            
            # Check if tags exist AFTER
            has_bdp = '<!-- BDP_START -->' in modified_markdown
            
            if not had_bdp and has_bdp:
                 logger.info("Found 'product' via BDP extractor")
                 newly_found_types.add('product')
                 # Wrap BDP content in MISSING_DOC tags for uniform extraction
                 # Using the new logic: wrap existing BDP tags
                 modified_markdown = _wrap_bdp_tags(modified_markdown)

        elif detect_func:
            detections = detect_func(modified_markdown)
            
            if detections:
                newly_found_types.add(doc_type)
                modified_markdown = mark_detected_sections(
                    modified_markdown, detections, doc_type
                )
                logger.info(f"✓ Found and marked {len(detections)} occurrence(s) of '{doc_type}'")
    
    return modified_markdown, newly_found_types


def _wrap_bdp_tags(markdown: str) -> str:
    """
    Wrap existing BDP tags with MISSING_DOC tags to enable extraction.
    Internal helper.
    """
    if "<!-- MISSING_DOC_START: product -->" in markdown:
        return markdown
        
    pattern = r'(<!-- BDP_START -->.*?<!-- BDP_END -->)'
    # Wrap capturing group 1 with MISSING_DOC tags
    replacement = r'<!-- MISSING_DOC_START: product -->\n\1\n<!-- MISSING_DOC_END: product -->'
    
    return re.sub(pattern, replacement, markdown, flags=re.DOTALL)


def mark_detected_sections(
    markdown: str, detections: List[Tuple[int, int]], doc_type: str
) -> str:
    """
    Mark detected sections with HTML comment balises.
    
    Args:
        markdown: Markdown content
        detections: List of (start_line, end_line) tuples
        doc_type: Document type to mark
        
    Returns:
        Modified markdown with balises inserted
    """
    lines = markdown.split('\n')
    
    # Sort detections in reverse order to insert from bottom up
    detections_sorted = sorted(detections, key=lambda x: x[0], reverse=True)
    
    for start_line, end_line in detections_sorted:
        # Insert end balise after the end line
        # Check bounds
        safe_end = min(end_line, len(lines) - 1)
        if safe_end < len(lines):
            lines.insert(safe_end + 1, f"<!-- MISSING_DOC_END: {doc_type} -->")
        else:
            lines.append(f"<!-- MISSING_DOC_END: {doc_type} -->")
        
        # Insert start balise before the start line
        safe_start = max(0, start_line)
        if safe_start < len(lines):
            lines.insert(safe_start, f"<!-- MISSING_DOC_START: {doc_type} -->")
    
    return '\n'.join(lines)


def detect_avis_fr(content: str) -> List[Tuple[int, int]]:
    """
    Detect French tender notices (Avis d'appel d'offres).
    Refined patterns based on S3 analysis.
    """
    lines = content.split('\n')
    detections = []
    
    # Header-focused start patterns
    # Matches: "AVIS D'APPEL D'OFFRES", "# AVIS D'APPEL D'OFFRES", "AVIS D'APPEL D'OFFRES OUVERT"
    start_pattern_regex = r"^#*\s*AVIS\s+D['’]APPEL\s+D['’]OFFRES"
    
    # End patterns
    end_patterns = [
        r"^Fait\s+à\s+.*",
        r"^Fait\s+à\s+.*le\s+.*",
    ]
    
    in_doc = False
    start_line = -1
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        if not in_doc:
            if re.search(start_pattern_regex, line_stripped, re.IGNORECASE):
                in_doc = True
                start_line = i
                logger.debug(f"Avis FR start detected at line {i}: {line[:50]}...")
        
        elif in_doc:
            # Check for end patterns
            for pattern in end_patterns:
                if re.search(pattern, line_stripped, re.IGNORECASE):
                    detections.append((start_line, i))
                    logger.debug(f"Avis FR end detected at line {i}")
                    in_doc = False
                    start_line = -1
                    break
            
            # Check for section separator or next header if not found
            if in_doc and re.match(r'^-{3,}$', line_stripped):
                 # Look ahead for next header to confirm separation
                 if i + 1 < len(lines) and lines[i+1].strip().startswith('#'):
                     detections.append((start_line, i - 1))
                     logger.debug(f"Avis FR end detected via separator at line {i}")
                     in_doc = False
                     start_line = -1

    if in_doc and start_line != -1:
        detections.append((start_line, len(lines) - 1))
    
    return detections


def detect_avis_ar(content: str) -> List[Tuple[int, int]]:
    """
    Detect Arabic tender notices.
    Refined patterns based on S3 analysis.
    """
    lines = content.split('\n')
    detections = []
    
    start_pattern_regex = r"^#*\s*إعلان\s+عن\s+طلب\s+عروض"
    
    # End is harder in Arabic OCR, usually rely on separator or specific closing layout
    # Assuming separator or end of file often works best
    
    in_doc = False
    start_line = -1
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        if not in_doc:
            if re.search(start_pattern_regex, line_stripped):
                in_doc = True
                start_line = i
                logger.debug(f"Avis AR start detected at line {i}")
        
        elif in_doc:
            if re.match(r'^-{3,}$', line_stripped):
                 if i + 1 < len(lines) and lines[i+1].strip().startswith('#'):
                     detections.append((start_line, i - 1))
                     in_doc = False
                     start_line = -1

    if in_doc and start_line != -1:
        detections.append((start_line, len(lines) - 1))
    
    return detections


def detect_declaration(content: str) -> List[Tuple[int, int]]:
    """
    Detect declaration sur l'honneur.
    
    Strategy:
    1. Start: "MODELE DE DECLARATION SUR L’HONNEUR" (robust)
    2. Validation: "Je soussigné" in next 80 lines.
    3. End: "Signature", "cachet", "Fait à".
    4. Extraction extends to end of page/file if signature found.
    """
    lines = content.split('\n')
    detections = []
    
    # Robust start pattern
    start_pattern_regex = r"^#*\s*(MOD[EÈ]LE\s+DE\s+(?:LA\s+)?)?D[EÈ]CLARATION\s+SUR\s+L['’]HONNEUR"
    
    in_doc = False
    start_line = -1
    found_end_keyword = False
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        line_lower = line.lower()
        
        if not in_doc:
            if re.search(start_pattern_regex, line_stripped, re.IGNORECASE):
                # Validation: Look for "Je soussigné" in next 80 lines
                preview_range = lines[i:min(i + 80, len(lines))]
                preview_text = '\n'.join(preview_range).lower()
                validation_terms = ["je soussigné", "nous soussignés"]
                
                if any(term in preview_text for term in validation_terms):
                    in_doc = True
                    start_line = i
                    found_end_keyword = False
                    logger.debug(f"Declaration start detected at line {i}")
        
        else:
            # Inside doc
            
            # Check for hard stops (allow separators if searching for signature, but stop at file headers)
            is_file_header = line.startswith("# File:")
            is_separator = re.match(r'^-{3,}$', line_stripped)
            is_page_marker = re.match(r'^##\s+[Pp]age\s+\d+', line_stripped)

            if found_end_keyword:
                # We found the signature block, now finding where the page/section ends
                if is_separator or is_file_header or is_page_marker:
                    detections.append((start_line, i - 1))
                    logger.debug(f"Declaration end detected at line {i-1}")
                    in_doc = False
                    start_line = -1
                    found_end_keyword = False
            
            else:
                # Looking for signature block
                if "signature" in line_lower or "cachet" in line_lower or "fait à" in line_lower:
                    found_end_keyword = True
                    logger.debug(f"Found end keyword at line {i}, extracting until end of page...")
                
                # Safeguards: Stop if we hit a new file header
                elif is_file_header:
                     logger.debug(f"Hit file header at line {i} without finding signature. Closing doc.")
                     detections.append((start_line, i - 1))
                     in_doc = False
                     start_line = -1
                     found_end_keyword = False

    if in_doc and start_line != -1:
        detections.append((start_line, len(lines) - 1))
    
    return detections


def detect_acte_engagement(content: str) -> List[Tuple[int, int]]:
    """
    Detect acte d'engagement.
    
    Strategy:
    1. Find start pattern.
    2. Validate by looking for "je soussigné" or "nous soussignés" in next 50 lines.
    3. If validated, searching for end keywords ("Signature", "cachet", "Fait à").
    4. Once end keywords are found, extend extraction to the "end of the page" 
       (next separator, file header, or page marker if present).
    """
    lines = content.split('\n')
    detections = []
    
    start_pattern_regex = r"^#*\s*(MOD[EÈ]LE\s+(?:DE\s+L|D)['’])?ACTE\s+D['’]ENGAGEMENT"
    
    in_doc = False
    start_line = -1
    found_end_keyword = False
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        line_lower = line.lower()
        
        if not in_doc:
            if re.search(start_pattern_regex, line_stripped, re.IGNORECASE):
                # Validation: Look for confirmation terms in next 50 lines
                preview_range = lines[i:min(i + 50, len(lines))]
                preview_text = '\n'.join(preview_range).lower()
                validation_terms = ["je soussigné", "nous soussignés"]
                
                if any(term in preview_text for term in validation_terms):
                    in_doc = True
                    start_line = i
                    found_end_keyword = False
                    logger.debug(f"Acte engagement start detected at line {i}")

        else:
            # We are in doc. Check for conditions to close or extend.
            
            # Check for hard stops (Separator, File Header, Page Marker)
            is_separator = re.match(r'^-{3,}$', line_stripped)
            is_file_header = line.startswith("# File:")
            is_page_marker = re.match(r'^##\s+[Pp]age\s+\d+', line_stripped)
            
            if found_end_keyword:
                # We are in the "extraction until end of page" phase
                if is_separator or is_file_header or is_page_marker:
                    detections.append((start_line, i - 1))
                    logger.debug(f"Acte engagement end detected at line {i-1}")
                    in_doc = False
                    start_line = -1
                    found_end_keyword = False
            
            else:
                 # Check for end keywords
                if "signature" in line_lower or "cachet" in line_lower or "fait à" in line_lower:
                    found_end_keyword = True
                    logger.debug(f"Found end keyword at line {i}, extracting until end of page...")
                
                # Check safeguards - if we hit start of new file (but allow separators/page breaks when traversing)
                elif is_file_header:
                    logger.debug(f"Hit file header at line {i} without finding signature keywords. Closing doc.")
                    detections.append((start_line, i - 1))
                    in_doc = False
                    start_line = -1
                    found_end_keyword = False

    if in_doc and start_line != -1:
        detections.append((start_line, len(lines) - 1))
    
    return detections


def extract_balised_documents(markdown_text: str) -> Tuple[str, List[LogicalDocument]]:
    """
    Extract content from balised sections and create LogicalDocument objects.
    
    Searches for HTML comment balises (<!-- MISSING_DOC_START: type --> ... <!-- MISSING_DOC_END: type -->),
    extracts the content, creates LogicalDocument objects with proper document types,
    and removes the balises from the markdown.
    
    Args:
        markdown_text: Markdown content with balised sections
        
    Returns:
        Tuple of (cleaned_markdown, extracted_documents)
        - cleaned_markdown: Markdown with balised sections removed
        - extracted_documents: List of LogicalDocument objects created from balised content
    """
    extracted_docs = []
    lines = markdown_text.split('\n')
    cleaned_lines = []
    
    # Stack for nested documents
    # Each item: {'type': str, 'content_lines': [], 'start_line_idx': int}
    doc_stack = []
    extraction_count = {}
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check for start balise
        start_match = re.match(r'^\s*<!-- MISSING_DOC_START: (\w+) -->\s*$', line)
        if start_match:
            doc_type = start_match.group(1)
            
            # Push new doc to stack
            doc_stack.append({
                'type': doc_type,
                'content_lines': [],
                'start_idx': i
            })
            
            if doc_type not in extraction_count:
                extraction_count[doc_type] = 0
            extraction_count[doc_type] += 1
            
            logger.debug(f"Found balise start for {doc_type} at line {i} (stack depth: {len(doc_stack)})")
            i += 1
            continue
        
        # Check for end balise
        end_match = re.match(r'^\s*<!-- MISSING_DOC_END: (\w+) -->\s*$', line)
        if end_match:
            doc_type = end_match.group(1)
            
            if doc_stack:
                # Check if matches top of stack
                if doc_stack[-1]['type'] == doc_type:
                    # Pop and create document
                    doc_data = doc_stack.pop()
                    content = '\n'.join(doc_data['content_lines']).strip()
                    
                    if content:
                        # Generate filename
                        occurrence = extraction_count[doc_type]
                        if occurrence > 1:
                            filename = f"extracted_{doc_type}_{occurrence}.md"
                        else:
                            filename = f"extracted_{doc_type}.md"
                        
                        extracted_doc = LogicalDocument(
                            original_filename=filename,
                            content=content,
                            doc_type=doc_type
                        )
                        extracted_docs.append(extracted_doc)
                        logger.info(
                            f"✓ Extracted '{doc_type}' document: {filename} "
                            f"({len(content)} chars)"
                        )
                    
                    if doc_stack:
                        # Append the content we just finished to the parent
                        doc_stack[-1]['content_lines'].extend(doc_data['content_lines'])
                        
                else:
                    logger.warning(
                        f"Mismatched balise end at line {i}: expected {doc_stack[-1]['type']}, got {doc_type}"
                    )
            else:
                 logger.warning(f"Found end balise for {doc_type} but no open document")
            
            i += 1
            continue
            
        # Handle content
        if doc_stack:
            # Add line to current top doc
            doc_stack[-1]['content_lines'].append(line)
        else:
            # Outside any doc, keep in cleaned output
            cleaned_lines.append(line)
            
        i += 1
    
    # Clean up markdown
    cleaned_markdown = '\n'.join(cleaned_lines)
    cleaned_markdown = re.sub(r'\n{4,}', '\n\n\n', cleaned_markdown)
    
    return cleaned_markdown, extracted_docs
