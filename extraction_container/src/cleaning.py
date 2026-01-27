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
        Splits a concatenated OCR markdown file into logical components.
        
        Logic:
        1. Split by '# File:' markers.
        2. Extract '> Document Type: ...' header.
        3. Search for '<!-- BDP_START --> ... <!-- BDP_END -->' blocks.
           - If found, extract them as separate 'product' documents.
           - Keep the surrounding text as documents of the original type.
        """
        docs = []
        # Regex to find file boundaries. 
        # Captures filename in group 1.
        pattern = r'(?m)^# File:\s*(.*?)$'
        
        matches = list(re.finditer(pattern, text))
        
        if not matches:
            # Assume single file if no headers found
            single_doc_type, clean_text = DocumentCleaners._extract_doc_type(text)
            return DocumentCleaners._process_bdp_blocks("unknown", clean_text, single_doc_type)
            
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
            
            # Process BDP blocks within this file
            file_docs = DocumentCleaners._process_bdp_blocks(filename, content, doc_type)
            docs.extend(file_docs)
            
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
            # We don't necessarily need to remove the header, but it's cleaner to keep it 
            # as part of content so LLM sees it, OR remove it. 
            # The prompt includes DOC TYPE: meta field, so removing it from content is fine/cleaner.
            # But let's leave it in the content for now to ensure no data loss, 
            # unless it interferes. It's just a Markdown blockquote.
            
        return doc_type, content

    @staticmethod
    def _process_bdp_blocks(filename: str, content: str, original_doc_type: str) -> List[LogicalDocument]:
        """
        Scans content for BDP tags and splits into multiple documents if found.
        """
        # Regex for BDP blocks
        # Flags: Dot matches newline
        bdp_pattern = r'<!-- BDP_START -->(.*?)<!-- BDP_END -->'
        
        parts = list(re.finditer(bdp_pattern, content, re.DOTALL))
        
        if not parts:
            # No BDP blocks, return single document
            return [LogicalDocument(
                original_filename=filename,
                content=content,
                doc_type=original_doc_type
            )]
            
        # If BDP blocks found, split
        results = []
        last_idx = 0
        
        for match in parts:
            start_bdp, end_bdp = match.span()
            
            # Text before BDP
            pre_text = content[last_idx:start_bdp].strip()
            if pre_text:
                results.append(LogicalDocument(
                    original_filename=filename,
                    content=pre_text,
                    doc_type=original_doc_type
                ))
            
            # The BDP content itself
            bdp_content = match.group(1).strip()
            if bdp_content:
                results.append(LogicalDocument(
                    original_filename=f"{filename} (Attached BDP)",
                    content=bdp_content,
                    doc_type="product" # FORCE type product for these blocks
                ))
                
            last_idx = end_bdp
            
        # Text after last BDP
        post_text = content[last_idx:].strip()
        if post_text:
            results.append(LogicalDocument(
                original_filename=filename,
                content=post_text,
                doc_type=original_doc_type
            ))
            
        return results

    @staticmethod
    def normalize_headers(text: str) -> str:
        """Standardizes headers (Article X -> ## ARTICLE X)."""
        # Article 1..99
        text = re.sub(r'^(#+)?\s*(ARTICLE|Article)\s*(\d+)', r'## ARTICLE \3', text, flags=re.MULTILINE)
        # Arabic Chapter
        text = re.sub(r'^#\s*الباب', r'## CHAPITRE', text, flags=re.MULTILINE)
        return text

