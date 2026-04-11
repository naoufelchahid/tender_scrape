import os

def swap_md_files(root_dir):
    """
    Parcourt récursivement le répertoire et intervertit les noms GEMINI.md <-> CLAUDE.md.
    """
    for root, dirs, files in os.walk(root_dir):
        # On ignore les dossiers cachés comme .git ou .venv
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        has_gemini = "GEMINI.md" in files
        has_claude = "CLAUDE.md" in files

        if has_gemini and has_claude:
            # Cas où les deux existent : on intervertit proprement via un fichier temporaire
            gemini_path = os.path.join(root, "GEMINI.md")
            claude_path = os.path.join(root, "CLAUDE.md")
            temp_path = os.path.join(root, "TEMP_SWAP.md")

            os.rename(gemini_path, temp_path)
            os.rename(claude_path, gemini_path)
            os.rename(temp_path, claude_path)
            print(f"🔄 Intervertis dans : {root}")
            
        elif has_gemini:
            # Uniquement GEMINI existe
            os.rename(os.path.join(root, "GEMINI.md"), os.path.join(root, "CLAUDE.md"))
            print(f"📝 Renommé : GEMINI.md -> CLAUDE.md dans {root}")
            
        elif has_claude:
            # Uniquement CLAUDE existe
            os.rename(os.path.join(root, "CLAUDE.md"), os.path.join(root, "GEMINI.md"))
            print(f"📝 Renommé : CLAUDE.md -> GEMINI.md dans {root}")

if __name__ == "__main__":
    # On lance le script sur le répertoire courant
    swap_md_files(".")
    print("\n✅ Terminé.")
