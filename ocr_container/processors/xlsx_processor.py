"""
XLSX processor to convert spreadsheets to markdown tables.
"""
import os
from typing import List, Optional
import pandas as pd
from openpyxl import load_workbook

from config import Config
from logger import logger


class XLSXProcessor:
    """XLSX to markdown table conversion processor."""
    
    def __init__(self):
        """Initialize XLSX processor."""
        pass
    
    def _dataframe_to_markdown(self, df: pd.DataFrame, sheet_name: str, table_num: int) -> str:
        """
        Convert pandas DataFrame to markdown table.
        
        Args:
            df: pandas DataFrame
            sheet_name: Name of the sheet
            table_num: Table number
            
        Returns:
            Markdown table string
        """
        if df.empty:
            return f"## {sheet_name}\n\n*Empty sheet*\n"
        
        # Replace NaN with empty string
        df = df.fillna('')
        
        # Convert all values to strings
        df = df.astype(str)
        
        # Create markdown header
        markdown_parts = [f"## {sheet_name}\n"]
        markdown_parts.append(f"**Table {table_num}**\n<table_start>")
        
        # Create table header
        headers = df.columns.tolist()
        header_line = "| " + " | ".join(str(h) for h in headers) + " |"
        separator_line = "|" + "|".join(["---" for _ in headers]) + "|"
        
        markdown_parts.append(header_line)
        markdown_parts.append(separator_line)
        
        # Create table rows
        for _, row in df.iterrows():
            row_values = [str(val) for val in row.values]
            row_line = "| " + " | ".join(row_values) + " |"
            markdown_parts.append(row_line)
            
        markdown_parts.append("<table_end>")
        
        return "\n".join(markdown_parts)
    
    def process(self, xlsx_path: str) -> str:
        """
        Process XLSX file and return markdown.
        
        Args:
            xlsx_path: Path to XLSX file
            
        Returns:
            Markdown text with all sheets converted to tables
        """
        logger.info(f"Processing XLSX: {xlsx_path}")
        
        try:
            # Read all sheets
            excel_file = pd.ExcelFile(xlsx_path)
            sheet_names = excel_file.sheet_names
            
            logger.info(f"Found {len(sheet_names)} sheets: {sheet_names}")
            
            markdown_parts = []
            
            for i, sheet_name in enumerate(sheet_names, 1):
                logger.info(f"Processing sheet: {sheet_name}")
                
                try:
                    # Read sheet
                    df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
                    
                    # Convert to markdown
                    sheet_markdown = self._dataframe_to_markdown(df, sheet_name, i)
                    markdown_parts.append(sheet_markdown)
                except Exception as e:
                    logger.warning(f"Error processing sheet {sheet_name}: {e}")
                    markdown_parts.append(f"## {sheet_name}\n\n*Error processing sheet: {str(e)}*\n")
            
            # Combine all sheets
            final_markdown = "\n---\n\n".join(markdown_parts)
            
            logger.info(f"Successfully processed XLSX with {len(sheet_names)} sheets")
            return final_markdown
        except Exception as e:
            logger.error(f"Error processing XLSX {xlsx_path}: {e}")
            raise


def process_xlsx(xlsx_path: str) -> str:
    """
    Process XLSX file to markdown.
    
    Args:
        xlsx_path: Path to XLSX file
        
    Returns:
        Markdown text
    """
    processor = XLSXProcessor()
    return processor.process(xlsx_path)
