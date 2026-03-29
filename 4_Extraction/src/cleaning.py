import re
from typing import List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class LogicalDocument:
    original_filename: str
    content: str
    doc_type: str = "unknown"
    page_start: Optional[int] = None
    page_end: Optional[int] = None

class DocumentCleaners:
    
    @staticmethod
    def split_concatenated_file(text: str) -> List[LogicalDocument]:
        """
        Splits a concatenated OCR markdown file into logical components based on '# File:' markers.
        """
        docs = []
        # Regex to find file boundaries. 
        pattern = r'(?m)^# File:\s*(.*?)$'
        
        matches = list(re.finditer(pattern, text))
        
        if not matches:
            # Assume single file if no headers found
            single_doc_type, clean_text = DocumentCleaners._extract_doc_type(text)
            return [LogicalDocument(
                original_filename="unknown",
                content=clean_text,
                doc_type=single_doc_type
            )]
            
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
            
            # Extract doc_type from header
            doc_type, content = DocumentCleaners._extract_doc_type(content)
            
            docs.append(LogicalDocument(
                original_filename=filename,
                content=content,
                doc_type=doc_type
            ))
            
        return docs

    @staticmethod
    def _extract_doc_type(content: str) -> tuple[str, str]:
        """
        Extracts Document Type from header and returns (doc_type, cleaned_content).
        Header format: > Document Type: <type>
        """
        doc_type = "unknown"
        # Match header line
        type_match = re.search(r'^\s*>\s*Document\s+Type:\s*(\w+)', content, re.IGNORECASE | re.MULTILINE)
        
        if type_match:
            doc_type = type_match.group(1).strip().lower()
            
        return doc_type, content

