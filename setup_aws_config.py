#!/usr/bin/env python3
"""
AWS Configuration Helper
Extracts Terraform outputs and updates .env file with AWS credentials
"""
import subprocess
import json
import os
from pathlib import Path
import re


def run_terraform_output():
    """Run terraform output and return JSON"""
    print("Fetching Terraform outputs...")
    
    try:
        result = subprocess.run(
            ['terraform', 'output', '-json'],
            cwd='terraform',
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running terraform output: {e}")
        print(f"stderr: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing terraform output: {e}")
        return None


def update_env_file(outputs):
    """Update .env file with AWS configuration from Terraform outputs"""
    env_file = Path('.env')
    
    if not env_file.exists():
        print("Warning: .env file not found. Creating new one...")
        env_content = []
    else:
        with open(env_file, 'r') as f:
            env_content = f.readlines()
    
    # Extract values from terraform outputs
    updates = {}
    
    if 's3_bucket_name' in outputs:
        updates['S3_BUCKET_NAME'] = outputs['s3_bucket_name']['value']
    
    if 's3_bucket_region' in outputs:
        updates['AWS_REGION'] = outputs['s3_bucket_region']['value']
    
    if 'db_address' in outputs:
        updates['DB_HOST'] = outputs['db_address']['value']
    
    if 'db_port' in outputs:
        updates['DB_PORT'] = str(outputs['db_port']['value'])
    
    if 'db_name' in outputs:
        updates['DB_NAME'] = outputs['db_name']['value']
    
    if 'db_username' in outputs:
        updates['DB_USER'] = outputs['db_username']['value']
    
    # Build full DATABASE_URL if we have all components
    if all(key in updates for key in ['DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER']):
        # Get password from existing .env or prompt
        db_password = None
        for line in env_content:
            if line.startswith('DB_PASSWORD='):
                db_password = line.split('=', 1)[1].strip()
                break
        
        if not db_password or db_password == 'your_password':
            print("\nNote: You need to set DB_PASSWORD in .env file")
            print("This should match the password you set in terraform.tfvars")
        else:
            updates['DATABASE_URL'] = (
                f"postgresql://{updates['DB_USER']}:{db_password}@"
                f"{updates['DB_HOST']}:{updates['DB_PORT']}/{updates['DB_NAME']}"
            )
    
    # Update env_content
    updated_lines = []
    updated_keys = set()
    
    for line in env_content:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith('#'):
            updated_lines.append(line)
            continue
        
        # Extract key from line
        if '=' in line:
            key = line.split('=', 1)[0].strip()
            if key in updates:
                updated_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)
    
    # Add new keys that weren't in the file
    if updated_keys:
        for key, value in updates.items():
            if key not in updated_keys:
                updated_lines.append(f"{key}={value}\n")
    
    # Write back to file
    with open(env_file, 'w') as f:
        f.writelines(updated_lines)
    
    return updates


def print_configuration(updates):
    """Print the configuration summary"""
    print("\n" + "=" * 80)
    print("AWS CONFIGURATION UPDATED")
    print("=" * 80)
    
    for key, value in sorted(updates.items()):
        # Don't print full DATABASE_URL as it may contain password
        if key == 'DATABASE_URL':
            # Extract host part only
            if '@' in value:
                host_part = value.split('@')[1]
                print(f"{key}: postgresql://***:***@{host_part}")
            else:
                print(f"{key}: {value}")
        elif 'PASSWORD' in key or 'SECRET' in key:
            print(f"{key}: ***")
        else:
            print(f"{key}: {value}")
    
    print("=" * 80)
    print("\nConfiguration has been written to .env file")
    print("\nIMPORTANT: Make sure to set the following in .env:")
    print("  - DB_PASSWORD (should match your terraform.tfvars db_password)")
    print("  - AWS_ACCESS_KEY_ID (your AWS access key)")
    print("  - AWS_SECRET_ACCESS_KEY (your AWS secret key)")
    print("\nOnce configured, you can run: python data_pusher.py")
    print("=" * 80)


def main():
    """Main entry point"""
    print("AWS Configuration Helper for Tender Scraper")
    print("=" * 80)
    
    # Check if terraform directory exists
    if not Path('terraform').exists():
        print("Error: terraform directory not found")
        return
    
    # Get terraform outputs
    outputs = run_terraform_output()
    if not outputs:
        print("Error: Could not fetch terraform outputs")
        print("\nMake sure you have run: cd terraform && terraform apply")
        return
    
    # Update .env file
    updates = update_env_file(outputs)
    
    # Print summary
    print_configuration(updates)


if __name__ == '__main__':
    main()
