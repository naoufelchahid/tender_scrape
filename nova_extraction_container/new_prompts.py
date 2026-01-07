    def _get_prompt_for_type(self, doc_type: str, content: str) -> str:
        """Get the specialized prompt for a document type.
        
        Args:
            doc_type: Type of document (product, specification, administrative, avis)
            content: Document content to analyze
            
        Returns:
            Complete prompt string
        """
        prompts = {
            'product': self._get_bdp_prompt(content),
            'specification': self._get_cps_prompt(content),
            'administrative': self._get_rc_prompt(content),
            'avis': self._get_avis_prompt(content)
        }
        
        return prompts.get(doc_type, self._get_generic_prompt(content))
    
    def _get_bdp_prompt(self, content: str) -> str:
        """Prompt for BDP (Bill of Quantities / Bordereau des Prix) documents.
        Focus: Table-aware extraction of individual product rows.
        """
        return f"""You are an expert Quantity Surveyor analyzing a Moroccan tender Bill of Quantities (Bordereau des Prix - BDP).
        
        YOUR GOAL: Extract every single product items from the pricing table(s) into separate, structured chunks.
        
        DOCUMENT CONTENT:
        {content}
        
        CRITICAL EXTRACTION RULES:
        1. **ONE ITEM = ONE CHUNK**: Create a separate chunk for EVERY meaningful row in the pricing table.
           - Do NOT merge multiple distinct items into one chunk.
           - Do NOT split a single item's multi-line description into huge separate chunks. Keep the full description together.
           
        2. **CONTENT RETENTION**: 
           - You MUST preserve the exact original French description.
           - Include all technical specs, dimensions, references, and norms mentioned for that item.
        
        3. **ATTRIBUTES EXTRACTION**:
           - **lot**: The Lot Number this item belongs to (look for headers like "LOT n°1: ..."). If implicit, infer from context.
           - **item_number**: The item number in the table (e.g., "1", "II.3", "5").
           - **quantity**: The quantity value (number).
           - **unit**: The unit of measurement (U, m2, m3, Ens, Forfait, etc.).
        
        4. **IGNORE**: Page numbers, running headers/footers, and subtotal/total rows that don't represent a physical item/service.
        
        OUTPUT FORMAT - WRAP EACH ITEM EXACTLY LIKE THIS:
        <!-- CHUNK:products:item_ID lot="LOT_NUM" designation="SHORT_DESC" quantity="QTY" unit="UNIT" -->
        [FULL ORIGINAL ROW CONTENT / DESCRIPTION]
        <!-- /CHUNK -->
        
        Example:
        <!-- CHUNK:products:1.2_server lot="1" designation="Serveur Rackable" quantity="2" unit="U" -->
        Item 1.2: Serveur de base de données
        Proc: 2x Intel Xeon Gold, 64GB RAM, 2x 480GB SSD RAID 1.
        Alimentation redondante. Garantie 3 ans sur site.
        <!-- /CHUNK -->
        """

    def _get_cps_prompt(self, content: str) -> str:
        """Prompt for CPS/CCTP (Cahier des Prescriptions Spéciales / Techniques).
        Focus: General Technical Specs, Product Specs, and embedded BDPs.
        """
        return f"""You are a Technical Writer analyzing a Moroccan tender CPS/CCTP (Technical Specifications) document.
        
        YOUR GOAL: Segment the document into logical, semantic chunks while preserving 100% of the relevant technical content.
        
        DOCUMENT CONTENT:
        {content}
        
        SEGMENTATION STRATEGY:
        1. **Article-Level Chunking**:
           - Treat each "ARTICLE" or major "SECTION" as a single chunk.
           - **NEVER** merge distinct articles (e.g., do not merge Art 3 and Art 4).
           - **NEVER** split a single logical Article into broken fragments unless it's huge (>2000 words).
        
        2. **CLASSIFICATION (Metadata 'type')**:
           - `products_specs`: Sections describing SPECIFIC technical requirements for materials, equipment, or works (e.g., "Spécifications du Béton", "Caractéristiques des PC").
           - `general_technical_specs`: Sections describing execution norms, standards, general methodology, quality control, site organization.
           - `products`: **CRITICAL** - If you find an embedded PRICING TABLE (Bordereau des Prix) within the text, extract those rows exactly like a BDP (One row = One chunk).
        
        3. **CONTENT PRESERVATION**:
           - Keep the full text of the article/section including headers.
           - Do not summarize. Copy the exact text.
        
        OUTPUT FORMATS:
        
        A. For Technical Articles (Specs/Norms):
        <!-- CHUNK:TYPE:Article_ID type="TYPE" title="ARTICLE_TITLE" -->
        [FULL TEXT OF THE ARTICLE]
        <!-- /CHUNK -->
        
        B. For Embedded Pricing Rows (if found):
        <!-- CHUNK:products:item_ID lot="LOT_NUM" -->
        [PRODUCT ROW CONTENT]
        <!-- /CHUNK -->
        
        Example A:
        <!-- CHUNK:products_specs:art_5 type="products_specs" title="Article 5: Menuiserie Aluminium" -->
        ARTICLE 5 : MENUISERIE ALUMINIUM
        L'aluminium sera de type... [Rest of text]
        <!-- /CHUNK -->
        """

    def _get_rc_prompt(self, content: str) -> str:
        """Prompt for RC/CCAG/CCAP (Administrative/Legal documents).
        Focus: Administrative clauses, eligibility, guarantees.
        """
        return f"""You are a Legal Analyst analyzing a Moroccan tender Administrative Document (RC, CCAP, CCAG).
        
        YOUR GOAL: Extract administrative clauses and requirements into clear, distinct chunks.
        
        DOCUMENT CONTENT:
        {content}
        
        SEGMENTATION STRATEGY:
        1. **Article-Level Chunking**: One Article/Clause = One Chunk.
        2. **Type**: Always usage `administrativ_specs`.
        3. **Key Sections to Isolate**:
           - Objet de l'appel d'offres
           - Cautionnement / Garanties (Provisoire, Définitive)
           - Critères d'admissibilité / Jugement
           - Modèle de déclaration / Engagement
        
        OUTPUT FORMAT:
        <!-- CHUNK:administrativ_specs:Article_ID type="administrativ_specs" title="ARTICLE_TITLE" -->
        [FULL TEXT OF THE CLAUSE]
        <!-- /CHUNK -->
        
        Example:
        <!-- CHUNK:administrativ_specs:caution type="administrativ_specs" title="Cautionnement Provisoire" -->
        ARTICLE 4 : CAUTIONNEMENT PROVISOIRE
        Le montant du cautionnement provisoire est fixé à...
        <!-- /CHUNK -->
        """

    def _get_avis_prompt(self, content: str) -> str:
        """Prompt for Tender Notice (Avis d'appel d'offres)."""
        return f"""You are analyzing a Tender Notice (Avis d'Appel d'Offres).
        
        YOUR GOAL: Extract the key summary data into a single comprehensive chunk.
        
        DOCUMENT CONTENT:
        {content}
        
        REQUIREMENTS:
        1. Capture: Client, Budget, Cautionnement, Date limite, Address for submission.
        2. Create a single chunk containing the full notice text.
        
        OUTPUT FORMAT:
        <!-- CHUNK:general_technical_specs:summary type="general_technical_specs" title="Avis Summary" -->
        [FULL TEXT OF THE NOTICE]
        <!-- /CHUNK -->
        """

    def _get_generic_prompt(self, content: str) -> str:
        """Generic prompt for other documents."""
        return f"""Analyze this document and segment it into logical sections (Chapters/Articles).
        
        DOCUMENT CONTENT:
        {content}
        
        OUTPUT FORMAT:
        <!-- CHUNK:general_technical_specs:Section_ID type="general_technical_specs" -->
        [SECTION CONTENT]
        <!-- /CHUNK -->
        """
