"""
Module for identifying and tagging "Bill of Quantities" (Bordereau des Prix) tables.
Priority:
1. If "Document Type: product", tag the entire document content.
2. Else, search for **Table N** and specific validation keywords using Regex.
"""

import logging
import re

logger = logging.getLogger(__name__)

def identify_and_tag_french_boq(markdown_text: str) -> str:
    """
    Identifies tables that look like a "Bill of Quantities" (BDP).
    Tags detected tables with <!-- BDP_START --> and <!-- BDP_END -->.

    Logic:
    - Iterate through the text, identifying logical file blocks (start with "# File:").
    - For each block:
        - Check "Document Type".
        - If "product" or "products":
            - Tag the whole block content (excluding header metadata) as BDP.
        - Else:
            - Run the Table-N regex detection logic on the lines of this block.

    Args:
        markdown_text: The full markdown content string.

    Returns:
        The modified markdown content with tags inserted.
    """
    if not markdown_text:
        return ""

    if not markdown_text:
        return ""

    lines = markdown_text.split('\n')
    n_lines = len(lines)
    
    # Keywords for detection (case-insensitive)
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
            # 1. Reconstruct block content to do regex search for <table_start>...<table_end>
            # We need byte offsets to map back to line numbers, so we join with newlines.
            block_lines = lines[block_start:block_end]
            block_text = "\n".join(block_lines)
            
            # Find all table blocks: <table_start> ... <table_end>
            # We use match.start() and match.end() to find where in the block text they are.
            # Then convert those character indices back to relative line numbers.
            
            # Simple approach: iterate through lines in the block
            # State machine tracking: inside_table or not
            
            table_start_line_rel = -1
            inside_table = False
            
            # header detection
            found_header_in_current_table = False
            
            for rel_i, line in enumerate(block_lines):
                stripped = line.strip()
                
                if "<table_start>" in stripped:
                    # New table starts
                    table_start_line_rel = rel_i
                    inside_table = True
                    found_header_in_current_table = False
                    continue
                
                if inside_table and not found_header_in_current_table:
                    # Look for header row (contains pipes)
                    if stripped.startswith('|') or stripped.count('|') >= 2:
                        # Analyze Header Row
                        match_count = 0
                        header_lower = stripped.lower()
                        
                        cells = [c.strip() for c in header_lower.split('|')]
                        for cell in cells:
                             cell_clean = cell.strip()
                             for keyword in BDP_KEYWORDS:
                                 # Exact match for short words (<3 chars), contains for others
                                 if len(keyword) < 3:
                                      if re.search(r'\b' + re.escape(keyword) + r'\b', cell_clean):
                                          match_count += 1
                                          break
                                 else:
                                      if keyword in cell_clean:
                                          match_count += 1
                                          break 
                        
                        if match_count >= 3:
                            # It's a BDP table!
                            # Find the start line absolute index
                            abs_start_idx = block_start + table_start_line_rel
                            
                            # Insert before <table_start>
                            # To be safe, insert just before the line containing <table_start>
                            insertions.append((abs_start_idx, "<!-- BDP_START -->"))
                            
                            found_header_in_current_table = True
                            
                            # Note: we still need to find <table_end> to close it
                        else:
                            # Not a BDP table header, or maybe header is next line?
                            # We only check the FIRST row that looks like a table row as header.
                            # So if this fails, we assume this table is not BDP (or header logic failed).
                            # To allow multi-line headers, we could make this more complex, but keeping simple for now.
                            found_header_in_current_table = True # Mark as "header processed" even if fail
                
                if "<table_end>" in stripped:
                    if inside_table:
                         # Table ends
                         if found_header_in_current_table:
                             # We only care if we decided it was a BDP table match_count >= 3 logic above
                             # But wait, we need to know if it was *actually* a BDP table.
                             # Re-check? No, we need state.
                             
                             # Let's refine state:
                             # We need to know if we already emitted BDP_START for this table.
                             # We can check insertions.
                             
                             # Check if the last insertion was BDP_START at abs_start_idx
                             abs_start_idx = block_start + table_start_line_rel
                             last_insertion_was_start = False
                             if insertions:
                                 last_idx, last_tag = insertions[-1]
                                 if last_idx == abs_start_idx and last_tag == "<!-- BDP_START -->":
                                     last_insertion_was_start = True
                             
                             if last_insertion_was_start:
                                  # Insert END tag after this line
                                  abs_end_idx = block_start + rel_i + 1
                                  insertions.append((abs_end_idx, "<!-- BDP_END -->"))
                    
                    inside_table = False
                    table_start_line_rel = -1

    # Apply insertions descending
    insertions.sort(key=lambda x: x[0], reverse=True)
    
    for idx, tag in insertions:
        if 0 <= idx <= len(lines):
             lines.insert(idx, tag)
        else:
             if idx >= len(lines):
                 lines.append(tag)
        
    return "\n".join(lines)
