import time
from rdflib import Graph, URIRef, RDF
from pyshacl import validate

g = Graph()
g.add((URIRef("http://example.com/Tender_A"), RDF.type, URIRef("http://www.tenderintelligence.io/ontology/tender-structure#Tenders")))
print("Loading shapes...")
sg = Graph().parse('ontology/shapes.ttl', format='turtle')
print("Loading ontology...")
og = Graph().parse('ontology/tender_structure.owl')

print("Starting validate...")
try:
    conforms, v_graph, v_text = validate(g, shacl_graph=sg, ont_graph=og, inference='none', meta_shacl=False, debug=True)
    print("Done:", conforms)
except Exception as e:
    print("Error:", e)
