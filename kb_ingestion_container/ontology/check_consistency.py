"""
Ontology Consistency Checker using owlapy (No-JVM version).
"""
import sys
from pathlib import Path
from owlapy.iri import IRI
from owlapy.owl_ontology import Ontology
from owlapy.owl_reasoner import StructuralReasoner
from owlapy.class_expression import OWLClass
from owlapy.vocab import OWLRDFVocabulary

def main():
    ontology_path = Path("/home/naoufel/projects/AO_scrape/ontology/tender_structure.owl")
    
    if not ontology_path.exists():
        print(f"❌ Error: {ontology_path} not found.")
        return

    print(f"🔍 Loading ontology: {ontology_path} ...")
    
    try:
        # Load the ontology using the base Ontology class
        onto = Ontology(IRI.create(f"file://{ontology_path.absolute()}"))
        
        print("⚙️ Initializing Structural Reasoner (Pure Python) ...")
        reasoner = StructuralReasoner(onto)
        
        print("\n📊 Axioms & Entities Check ...")
        owlready_onto = onto._onto
        classes_count = len(list(owlready_onto.classes()))
        individuals_count = len(list(owlready_onto.individuals()))
        data_props_count = len(list(owlready_onto.data_properties()))
        object_props_count = len(list(owlready_onto.object_properties()))
        general_axioms_count = len(list(owlready_onto.general_class_axioms()))
        triples_count = len(list(owlready_onto.get_triples()))
        
        print("📈 Ontology Statistics:")
        print(f"  - Classes: {classes_count}")
        print(f"  - Individuals: {individuals_count}")
        print(f"  - Object Properties: {object_props_count}")
        print(f"  - Data Properties: {data_props_count}")
        print(f"  - General Class Axioms: {general_axioms_count}")
        print(f"  - Total RDF Triples (Foundational Axioms): {triples_count}\n")
        
        print("⚖️ Checking class satisfiability ...")
        classes = list(onto.classes_in_signature())
        print(f"📦 Signature size: {len(classes)} classes.")
        
        unsatisfiable = []
        nothing = OWLClass(OWLRDFVocabulary.OWL_NOTHING.iri)
        
        for cls in classes:
            if cls.is_owl_nothing():
                continue
            
            # Check if class is equivalent to Nothing
            equivs = list(reasoner.equivalent_classes(cls))
            if nothing in equivs:
                unsatisfiable.append(cls)
        
        if unsatisfiable:
            print(f"⚠️ Found {len(unsatisfiable)} unsatisfiable classes (equivalent to owl:Nothing):")
            for cls in unsatisfiable:
                print(f"  - {cls.iri.as_str()}")
        
        print("\n🔍 Checking Object Properties Inference ...")
        object_properties = list(onto.object_properties_in_signature())
        print(f"Found {len(object_properties)} object properties. Inferring characteristics...")
        
        for op in object_properties:
            op_str = op.iri.as_str() if hasattr(op, 'iri') else str(op)
            
            # Fetch inferred domains
            domains = list(reasoner.object_property_domains(op, direct=True))
            dom_strs = [d.iri.as_str() if hasattr(d, 'iri') else str(d) for d in domains]
            
            # Fetch inferred ranges
            ranges = list(reasoner.object_property_ranges(op, direct=True))
            rng_strs = [r.iri.as_str() if hasattr(r, 'iri') else str(r) for r in ranges]
            
            # Fetch sub-properties
            sub_props = list(reasoner.sub_object_properties(op, direct=True))
            sp_strs = [p.iri.as_str() if hasattr(p, 'iri') else str(p) for p in sub_props]
            
            # Only print if there is something interesting inferred
            if dom_strs or rng_strs or sp_strs:
                print(f"\n  Object Property: {op_str}")
                if dom_strs:
                    print(f"    - Inferred Domains: {', '.join(dom_strs)}")
                if rng_strs:
                    print(f"    - Inferred Ranges: {', '.join(rng_strs)}")
                if sp_strs:
                    print(f"    - Sub-Properties: {', '.join(sp_strs)}")
                    
    except Exception as e:
        print(f"❌ Critical Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
