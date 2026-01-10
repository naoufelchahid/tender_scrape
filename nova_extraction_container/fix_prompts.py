"""
Script to fix LangChain prompt template variable escaping.
Escapes all curly braces in JSON examples within prompts.
"""
import re

def escape_json_in_prompts(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    in_prompt = False
    in_json_example = False
    fixed_lines = []
    
    for i, line in enumerate(lines):
        # Detect if we're in a prompt method
        if 'def _create_' in line and '_prompt' in line:
            in_prompt = True
        
        # Detect JSON example start
        if in_prompt and ('Return ONLY valid JSON' in line or 'Return ONLY JSON' in line):
            in_json_example = True
        
        # Detect prompt method end
        if in_prompt and line.strip().startswith('def ') and i > 0:
            in_prompt = False
            in_json_example = False
        
        # Escape curly braces in JSON examples
        if in_json_example and ('{' in line or '}' in line):
            # Don't escape f-string braces or already escaped braces
            if not line.strip().startswith('f"""') and '{{' not in line:
                line = line.replace('{', '{{').replace('}', '}}')
        
        fixed_lines.append(line)
    
    with open(filepath, 'w') as f:
        f.writelines(fixed_lines)
    
    print(f"Fixed {filepath}")

if __name__ == '__main__':
    escape_json_in_prompts('src/nova_extractor.py')
