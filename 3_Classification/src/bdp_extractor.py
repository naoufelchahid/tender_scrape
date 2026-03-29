"""
Pipeline Stage: Classification Container  
Enhanced BDP extractor supporting both <table_start> markers and markdown pipe tables
"""

import logging
import re

logger = logging.getLogger(__name__)

def identify_and_tag_french_boq(markdown_text: str) -> str:
    """
    Identifies tables that look like a "Bill of Quantities" (BDP).
    Tags detected tables with <!-- BDP_START --> and <!-- BDP_END -->.
    
    Supports two table formats:
    1. Tables with <table_start> and <table_end> markers (legacy OCR format)
    2. Markdown pipe tables (current OCR format)

    Logic:
    - Iterate through the text, identifying logical file blocks (start with "# File:").
    - For each block:
        - Check "Document Type".
        - If "product" or "products":
            - Tag the whole block content (excluding header metadata) as BDP.
        - Else:
            - Run table detection logic (both marker-based and markdown pipe tables).

    Args:
        markdown_text: The full markdown content string.

    Returns:
        The modified markdown content with tags inserted.
    """
    if not markdown_text:
        return ""

    lines = markdown_text.split('\n')
    n_lines = len(lines)
    
    # Keywords for BDP detection (case-insensitive)
    BDP_KEYWORDS = {
        "désignation", "designation", 
        "unité", "unite", "u",
        "quantité", "quantite", "qte", "qté",
        "prix unitaire", "prix_unitaire", "p.u", "pu",
        "montant", 
        "total", "pt",
        "numéro", "numero", "n°",
        "prix"
    }

    insertions = []
    
    # Find file boundaries
    file_starts = []
    for i, line in enumerate(lines):
        if line.startswith("# File:"):
            file_starts.append(i)
    
    # Add EOF
    file_starts.append(n_lines)
    
    # Process each block
    for k in range(len(file_starts) - 1):
        block_start = file_starts[k]
        block_end = file_starts[k+1]
        
        # Analyze block header to find Document Type
        doc_type = None
        content_start_offset = 0
        
        for local_i in range(block_start, min(block_start + 10, block_end)):
            line = lines[local_i].strip()
            if line.lower().startswith("> document type:"):
                 parts = line.split(":", 1)
                 if len(parts) > 1:
                     doc_type = parts[1].strip().lower()
            
            if line.lower().startswith("> document type:") and content_start_offset == 0:
                 content_start_offset = local_i + 1
        
        is_product = doc_type in ["product", "products"]
        
        if is_product:
            logger.info(f"File at line {block_start} is classification 'product'. Tagging entire content.")
            tag_start = content_start_offset if content_start_offset > 0 else block_start + 1
            insertions.append((tag_start, "<!-- BDP_START -->"))
            insertions.append((block_end, "<!-- BDP_END -->"))
            
        else:
            # Detect tables in this block (both formats)
            detect_and_tag_tables_in_block(lines, block_start, block_end, BDP_KEYWORDS, insertions)

    # Apply insertions descending
    insertions.sort(key=lambda x: x[0], reverse=True)
    
    for idx, tag in insertions:
        if 0 <= idx <= len(lines):
             lines.insert(idx, tag)
        else:
             if idx >= len(lines):
                 lines.append(tag)
        
    return "\n".join(lines)


def detect_and_tag_tables_in_block(lines, block_start, block_end, bdp_keywords, insertions):
    """
    Detect and tag BDP tables within a block.
    Handles both <table_start>/<table_end> format and markdown pipe tables.
    """
    block_lines = lines[block_start:block_end]
    
    # Try marker-based detection first
    if detect_marker_tables(block_lines, block_start, bdp_keywords, insertions):
        return
    
    # Fall back to markdown table detection
    detect_markdown_pipe_tables(block_lines, block_start, bdp_keywords, insertions)


def detect_marker_tables(block_lines, block_start, bdp_keywords, insertions):
    """
    Detect tables with <table_start> and <table_end> markers.
    Returns True if any marker-based tables were found.
    """
    table_start_line_rel = -1
    inside_table = False
    found_header_in_current_table = False
    found_any_markers = False
    
    for rel_i, line in enumerate(block_lines):
        stripped = line.strip()
        
        if "<table_start>" in stripped:
            found_any_markers = True
            table_start_line_rel = rel_i
            inside_table = True
            found_header_in_current_table = False
            continue
        
        if inside_table and not found_header_in_current_table:
            # Look for header row (contains pipes)
            if stripped.startswith('|') or stripped.count('|') >= 2:
                match_count = count_bdp_keywords(stripped, bdp_keywords)
                
                if match_count >= 3:
                    # It's a BDP table!
                    abs_start_idx = block_start + table_start_line_rel
                    insertions.append((abs_start_idx, "<!-- BDP_START -->"))
                    found_header_in_current_table = True
                else:
                    found_header_in_current_table = True
        
        if "</table_end>" in stripped:
            if inside_table:
                 if found_header_in_current_table:
                     abs_start_idx = block_start + table_start_line_rel
                     last_insertion_was_start = False
                     if insertions:
                         last_idx, last_tag = insertions[-1]
                         if last_idx == abs_start_idx and last_tag == "<!-- BDP_START -->":
                             last_insertion_was_start = True
                     
                     if last_insertion_was_start:
                          abs_end_idx = block_start + rel_i + 1
                          insertions.append((abs_end_idx, "<!-- BDP_END -->"))
            
            inside_table = False
            table_start_line_rel = -1
    
    return found_any_markers


def detect_markdown_pipe_tables(block_lines, block_start, bdp_keywords, insertions):
    """
    Detect markdown pipe tables (|...|...|) and tag those with BDP keywords.
    Enhanced to:
    1. Capture preceding checks/titles/descriptions.
    2. Handle multi-page tables (tables interrupted by page breaks/etc).
    """
    i = 0
    n = len(block_lines)
    
    while i < n:
        line = block_lines[i]
        stripped = line.strip()
        
        # Check if this line looks like the START of a table header
        if stripped.count('|') >= 2:
            match_count = count_bdp_keywords(stripped, bdp_keywords)
            
            if match_count >= 3:
                # Found a BDP table header!
                
                # 1. Look backwards for Description/Title
                start_rel_idx = find_bdp_description_start(block_lines, i)
                
                # 2. Look forwards for end of table (handling interruptions)
                end_rel_idx = find_bdp_table_end(block_lines, i, n)
                
                abs_start = block_start + start_rel_idx
                abs_end = block_start + end_rel_idx + 1 # Insert AFTER the last line
                
                # Add Tags
                insertions.append((abs_start, "<!-- BDP_START -->"))
                insertions.append((abs_end, "<!-- BDP_END -->"))
                
                logger.info(f"Tagged continuous BDP table from line {abs_start} to {abs_end}")
                
                # Jump iterator to end of this table
                i = end_rel_idx + 1
                continue
                
        i += 1


def find_bdp_description_start(lines, header_idx):
    """
    Scan backwards from the table header to find the logical start of the BDP section.
    We look for keywords like "Bordereau", "Détail", "Objet", or "Prix n°".
    We allow capturing a block of text text if it seems relevant.
    """
    # Look back up to 20 lines
    search_limit = max(0, header_idx - 20)
    best_start = header_idx
    
    found_keyword = False
    
    # Keywords indicating start of section
    START_KEYWORDS = ["bordereau", "détail estimatif", "detail estimatif", "objet", "b.d.p", "bdp", "prix n°"]
    
    # We iterate backwards.
    # If we find a keyword, we mark that line as potential start.
    # We keep going up to see if there are earlier keywords.
    
    for i in range(header_idx - 1, search_limit - 1, -1):
        line = lines[i].strip()
        line_lower = line.lower()
        
        if not line:
            continue
            
        # Stop boundaries
        if line.startswith("# File:") or ("|" in line and line.count('|') >= 2):
            break
            
        if any(kw in line_lower for kw in START_KEYWORDS):
            best_start = i
            found_keyword = True
        elif found_keyword:
            pass
            
    return best_start


def find_bdp_table_end(lines, header_idx, max_idx):
    """
    Scan forwards to find the end of the table.
    Tolerates interruptions like "## Page X", "---", or empty lines, 
    AS LONG AS the table resumes afterwards.
    """
    last_table_line = header_idx
    i = header_idx + 1
    consecutive_non_table_lines = 0
    MAX_GAP = 10  # Max lines of interruption allowed
    
    while i < max_idx:
        line = lines[i].strip()
        
        is_table_row = ('|' in line) and (len(line) > 1)
        
        if is_table_row:
            # It is a table row!
            last_table_line = i
            consecutive_non_table_lines = 0 # Reset gap counter
        else:
            # Not a table row. Is it a permissible interruption?
            consecutive_non_table_lines += 1
            
            if consecutive_non_table_lines > MAX_GAP:
                # Too much gap, table definitely ended at last_table_line
                break
            
            # Additional check: If we hit a NEW "File:" marker, definitely stop
            if line.startswith("# File:"):
                break
                
        i += 1
        
    return last_table_line


def count_bdp_keywords(header_text, bdp_keywords):
    """Count how many BDP keywords are present in the header text."""
    match_count = 0
    header_lower = header_text.lower()
    cells = [c.strip() for c in header_lower.split('|')]
    
    for cell in cells:
        cell_clean = cell.strip()
        for keyword in bdp_keywords:
            # Exact match for short words (<3 chars), contains for others
            if len(keyword) < 3:
                 # Use whitespace boundaries instead of \b to handle symbols like '°'
                 if re.search(r'(?:^|\s)' + re.escape(keyword) + r'(?:\s|$)', cell_clean):
                     match_count += 1
                     break
            else:
                 if keyword in cell_clean:
                     match_count += 1
                     break
    
    return match_count
