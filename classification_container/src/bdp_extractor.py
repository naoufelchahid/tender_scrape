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
    
    # We need to process by file blocks.
    # Scan for # File: lines.
    # Store blocks as (start_line_idx, end_line_idx) - end exclusive (start of next file or EOF)
    
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
        
        # Analyze block header to find Document Type and start of content
        # Header usually:
        # # File: ...
        # > Document Type: ...
        # [Empty Line]
        # ## Page X ...
        
        doc_type = None
        content_start_offset = 0
        
        # Scan first few lines of block for metadata
        # We assume metadata is at top. If > Document Type appears later, we might miss it if we limit excessively,
        # but typically it's line 2 or 3 of the block.
        
        for local_i in range(block_start, min(block_start + 10, block_end)):
            line = lines[local_i].strip()
            if line.lower().startswith("> document type:"):
                 parts = line.split(":", 1)
                 if len(parts) > 1:
                     doc_type = parts[1].strip().lower()
            
            # Heuristic for content start: After Document Type line? Or simple heuristic?
            # If we tag as product, we probably want to start tagging AFTER the 'Document Type' line.
            # Or maybe after the first blank line following it?
            # Let's say content starts line after Doc Type for safety.
            if line.lower().startswith("> document type:") and content_start_offset == 0:
                 content_start_offset = local_i + 1
        
        # Determine strategy
        is_product = doc_type in ["product", "products"]
        
        if is_product:
            logger.info(f"File at line {block_start} is classification 'product'. Tagging entire content.")
            
            # Start tag: after metadata (content_start_offset), or if not found, just after # File line?
            # Using content_start_offset if found, else block_start + 1
            tag_start = content_start_offset if content_start_offset > 0 else block_start + 1
            
            # End tag: block_end
            # We insert END tag first in our list logic if we process normally, but here we process blocks.
            # We add to global insertions list.
            
            insertions.append((tag_start, "<!-- BDP_START -->"))
            insertions.append((block_end, "<!-- BDP_END -->"))
            
        else:
            # Run Regex Table Finding Logic within [block_start, block_end]
            # We limit 'i' to this range.
            
            processed_lines_in_block = set()
            
            i = block_start
            while i < block_end:
                if i in processed_lines_in_block:
                    i += 1
                    continue

                line = lines[i].strip()
                
                # 1. Search for "**Table N**"
                table_tag_match = re.search(r'\*\*Table\s+\d+\*\*', line, re.IGNORECASE)
                
                if table_tag_match:
                    table_tag_line_index = i
                    
                    # 2. Look ahead for table content
                    table_start_index = -1
                    header_row_content = ""
                    
                    lookahead_limit_start = 10 
                    j_start = i + 1
                    
                    while j_start < min(i + 1 + lookahead_limit_start, block_end):
                        next_line = lines[j_start].strip()
                        if next_line and (next_line.startswith('|') or next_line.count('|') >= 2):
                            table_start_index = j_start
                            header_row_content = next_line
                            break
                        j_start += 1
                    
                    if table_start_index != -1:
                        # 3. Analyze Header Row
                        match_count = 0
                        header_lower = header_row_content.lower()
                        
                        cells = [c.strip() for c in header_lower.split('|')]
                        for cell in cells:
                            cell_clean = cell.strip()
                            for keyword in BDP_KEYWORDS:
                                if len(keyword) < 3:
                                    if re.search(r'\b' + re.escape(keyword) + r'\b', cell_clean):
                                        match_count += 1
                                        break
                                else:
                                    if keyword in cell_clean:
                                        match_count += 1
                                        break 
                        
                        if match_count >= 3:
                             logger.info(f"BDP Table found at line {table_start_index} (Tag at {table_tag_line_index}) in non-product file. Matches: {match_count}")
                             
                             # 4. Find Table End with Continuation
                             current_idx = table_start_index
                             last_valid_table_line = table_start_index
                             
                             while current_idx < block_end - 1:
                                 next_idx = current_idx + 1
                                 
                                 nl = lines[next_idx].strip()
                                 if nl and (nl.startswith('|') or nl.count('|') >= 2):
                                     current_idx = next_idx
                                     last_valid_table_line = current_idx
                                 else:
                                     # Gap lookahead
                                     gap_lookahead = 15
                                     found_continuation = False
                                     for gap_k in range(1, gap_lookahead + 1):
                                         check_idx = next_idx + gap_k
                                         if check_idx >= block_end:
                                             break
                                         check_line = lines[check_idx].strip()
                                         if check_line and (check_line.startswith('|') or check_line.count('|') >= 2):
                                             current_idx = check_idx
                                             last_valid_table_line = current_idx
                                             found_continuation = True
                                             break
                                     if not found_continuation:
                                         break
                             
                             table_end_index = last_valid_table_line
                             
                             insertions.append((table_tag_line_index, "<!-- BDP_START -->"))
                             insertions.append((table_end_index + 1, "<!-- BDP_END -->"))
                             
                             # Mark skipped
                             for k in range(table_tag_line_index, table_end_index + 1):
                                 processed_lines_in_block.add(k)
                             
                             i = table_end_index
                             continue 
    
                i += 1

    # Apply insertions descending
    insertions.sort(key=lambda x: x[0], reverse=True)
    
    for idx, tag in insertions:
        # Check if idx is valid (minor safety)
        if 0 <= idx <= len(lines):
             lines.insert(idx, tag)
        else:
             # Should not happen given logic, but safe to append if at end?
             if idx >= len(lines):
                 lines.append(tag)
        
    return "\n".join(lines)
