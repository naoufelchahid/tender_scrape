"""
Unified Document Processor using Docling.
Replaces legacy disparate processors for PDF, DOCX, XLSX, and Images.
"""
import os
import re
import yaml
import subprocess
import shutil
from pathlib import Path

import torch
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableStructureOptions,
    AcceleratorOptions,
    AcceleratorDevice,
)
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

from logger import logger


def _assert_gpu_available() -> None:
    """
    Assert that a CUDA GPU is available. Raises RuntimeError at startup if not.
    This service requires GPU — there is no CPU fallback.
    """
    if not torch.cuda.is_available():
        raise RuntimeError(
            "No CUDA GPU detected. This service requires GPU. "
            "Ensure the container is started with --gpus all or equivalent."
        )

    device_name = torch.cuda.get_device_name(0)
    total_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
    logger.info("=" * 80)
    logger.info(f"🚀 GPU DETECTED: {device_name}")
    logger.info(f"📊 VRAM: {total_memory:.2f} GB")
    logger.info(f"🔧 CUDA Version: {torch.version.cuda}")
    logger.info("=" * 80)


class DocumentProcessor:
    """
    Unified processor for transforming documents to GraphRAG-optimized Markdown.
    Uses Docling for high-fidelity conversion including OCR and tables.
    Supports GPU acceleration when available.
    """
    
    def __init__(self):
        """Initialize Docling converter with OCR and Table options."""
        # Fail fast if no GPU — this service does not support CPU fallback
        _assert_gpu_available()

        # Configure Pipeline Options for OCR and Tables
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.do_table_structure = True

        # Explicitly target CUDA — Docling must not fall back to CPU
        pipeline_options.accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice.CUDA
        )

        # Configure Table Options
        table_options = TableStructureOptions()
        pipeline_options.table_structure_options = table_options

        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend
                )
            }
        )

        logger.info("✅ DocumentProcessor initialized with Docling (OCR enabled, Device: CUDA)")

    def process(self, file_path: str) -> str:
        """
        Process any supported file type to Markdown.
        Handles legacy formats (.doc, .xls, .ppt) by converting them first.
        
        Args:
            file_path: Absolute path to the file.
            
        Returns:
            Cleaned, enriched Markdown string.
        """
        try:
            logger.info(f"Starting processing for: {file_path}")
            
            # 0. Handle Legacy Formats (doc -> docx, xls -> xlsx)
            file_path = self._convert_if_legacy(file_path)
            
            # 1. Convert to Markdown using Docling
            conv_result = self.converter.convert(file_path)
            markdown_content = conv_result.document.export_to_markdown()
            
            # 2. Post-process (Strict Hierarchy & Noise Removal)
            cleaned_markdown = self._post_process_markdown(markdown_content)
            
            # 3. Enrich with Metadata
            final_output = self._enrich_metadata(cleaned_markdown, file_path)
            
            logger.info(f"Successfully processed {file_path}")
            return final_output

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {str(e)}", exc_info=True)
            # Return error block but don't crash service
            return self._create_error_output(file_path, str(e))

    def _post_process_markdown(self, text: str) -> str:
        """
        Enforce header hierarchy and strip common noise.
        Rules:
        - Articles and Clauses -> H3 (###)
        - Demote headers below Article level
        - Remove headers for noise (NB, Important, À savoir)
        """
        lines = text.split('\n')
        cleaned_lines = []
        
        # Regex patterns
        page_pat = re.compile(r'^\s*(Page\s+\d+|[\d]+(\s*/\s*[\d]+)?)\s*$', re.IGNORECASE)
        article_pat = re.compile(r'^\s*#{1,6}\s*(ARTICLE|CLAUSE)\s+.*', re.IGNORECASE)
        noise_pat = re.compile(r'^\s*#{1,6}\s*(NB|Important|À savoir)(\s*:.*)?', re.IGNORECASE)
        header_pat = re.compile(r'^\s*(#{1,6})\s*(.*)')
        
        inside_article_block = False
        
        for line in lines:
            line_str = line.strip()
            
            # 1. Skip empty
            if not line_str:
                cleaned_lines.append(line)
                continue
                
            # 2. Filter Page numbers
            if page_pat.match(line_str):
                continue

            # 3. Check for Headers
            header_match = header_pat.match(line_str)
            if header_match:
                marker = header_match.group(1)
                content = header_match.group(2).strip()
                
                # Rule: Remove Noise Headers -> Convert to Bold
                if noise_pat.match(line_str):
                    # Strip the hash, make bold
                    cleaned_lines.append(f"**{content}**")
                    continue
                
                # Rule: Article / Clause -> H3
                # Check if it contains "ARTICLE" or "CLAUSE" (case-insensitive)
                # We use regex to match the keyword at start of content
                if re.match(r'^(ARTICLE|CLAUSE)\b', content, re.IGNORECASE):
                    inside_article_block = True
                    cleaned_lines.append(f"### {content}")
                    continue
                
                # Rule: Below article should not have headers
                if inside_article_block:
                    # If we encounter a new "Section" or "Chapter" or "Title" we might exit article block?
                    # But if it's just "1 - something" or "a) something", we demote.
                    # Heuristic: If it's NOT an Article/Clause, and we are inside one, 
                    # check if it looks like a higher level section (Title)? 
                    # If uncertain, demote to bold to respect "below article should not have headers"
                    # Exception: If it's a huge header like "CHAPITRE II", we probably should exit article block.
                    # Let's check for strong structural keywords to break out.
                    if re.match(r'^(CHAPITRE|TITRE|PARTIE|SECTION)\b', content, re.IGNORECASE):
                        inside_article_block = False
                        # Keep it as is (maybe normalize to H2?)
                        cleaned_lines.append(f"## {content}")
                    else:
                        # Demote to bold
                        cleaned_lines.append(f"**{content}**")
                else:
                    # Not inside article, handle normally.
                    # Maybe normalize structure? docling output is trusted otherwise.
                    cleaned_lines.append(line)
            else:
                # Regular line
                cleaned_lines.append(line)
            
        return '\n'.join(cleaned_lines)

    def _enrich_metadata(self, content: str, file_path: str) -> str:
        """
        Prepend YAML frontmatter.
        """
        path_obj = Path(file_path)
        
        metadata = {
            'filename': path_obj.name,
            'file_type': path_obj.suffix.lower().lstrip('.'),
            'processed_at': str(os.environ.get('processed_at', '')) # Placeholder or real
        }
        
        # We try to guess page count from content markers if possible or just omit if unknown
        # Simpler: just basic info
        
        yaml_block = yaml.dump(metadata, default_flow_style=False)
        return f"---\n{yaml_block}---\n\n{content}"

    def _create_error_output(self, file_path: str, error_msg: str) -> str:
        """Generate a valid markdown error file."""
        return f"""---
filename: {os.path.basename(file_path)}
file_type: error
---

# Error Processing File

**File**: `{file_path}`
**Error**: {error_msg}

This file could not be processed by the Docling pipeline.
"""

    def _convert_if_legacy(self, file_path: str) -> str:
        """
        Convert legacy formats (.doc, .xls, .ppt) to modern equivalents using LibreOffice.
        Returns the new path if converted, or original path if not needed.
        """
        file_path_obj = Path(file_path)
        ext = file_path_obj.suffix.lower()
        
        legacy_map = {
            '.doc': '.docx',
            '.xls': '.xlsx',
            '.ppt': '.pptx'
        }
        
        if ext not in legacy_map:
            return file_path
        
        logger.info(f"Detected legacy format {ext}. Converting to {legacy_map[ext]}...")
        
        try:
            # Output directory is same as input (temp dir)
            out_dir = file_path_obj.parent
            
            # Run LibreOffice headless conversion
            # --convert-to xlsx --outdir /app/temp /app/temp/file.xls
            target_fmt = legacy_map[ext].lstrip('.')
            
            cmd = [
                "soffice",
                "--headless",
                "--convert-to", target_fmt,
                "--outdir", str(out_dir),
                str(file_path)
            ]
            
            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True,
                timeout=60 # 1 minute timeout per file
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
            
            # Construct new filename
            new_filename = file_path_obj.stem + legacy_map[ext]
            new_path = out_dir / new_filename
            
            if not new_path.exists():
                raise FileNotFoundError(f"Converted file not found at {new_path}")
                
            logger.info(f"Successfully converted to {new_path}")
            return str(new_path)
            
        except Exception as e:
            logger.error(f"Failed to convert legacy file {file_path}: {e}")
            return file_path
