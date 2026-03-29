"""
Pipeline Stage: Classification Container
Document splitter - extracts logical documents from concatenated OCR markdown
"""

import re
from typing import List
from dataclasses import dataclass


@dataclass
class LogicalDocument:
    """Represents a single logical document extracted from concatenated markdown."""
    original_filename: str
    content: str
    doc_type: str = "unknown"


def split_concatenated_file(text: str) -> List[LogicalDocument]:
    """
    Splits a concatenated OCR markdown file into logical components.
    
    Expected format:
        # File: filename1.docx
        ... content ...
        ---
        # File: filename2.pdf
        ...
    
    Args:
        text: Concatenated markdown text
        
    Returns:
        List of LogicalDocument objects
    """
    docs = []
    # Regex to find file boundaries. 
    # Captures filename in group 1.
    pattern = r'(?m)^# File:\s*(.*?)$'
    
    matches = list(re.finditer(pattern, text))
    
    if not matches:
        # Assume single file if no headers found
        return [LogicalDocument(original_filename="unknown", content=text, doc_type="unknown")]
        
    for i, match in enumerate(matches):
        filename = match.group(1).strip()
        start_idx = match.end()
        
        # End index is start of next match or end of string
        if i + 1 < len(matches):
            end_idx = matches[i+1].start()
        else:
            end_idx = len(text)
            
        content = text[start_idx:end_idx].strip()
        
        # Clean generic separators if present at start/end
        content = re.sub(r'^---\s*', '', content)
        content = re.sub(r'\s*---$', '', content)
        
        docs.append(LogicalDocument(
            original_filename=filename,
            content=content,
            doc_type="unknown"  # Will be classified later
        ))
        
    return docs
