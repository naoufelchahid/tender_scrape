from jena_client import JenaClient

# Initialize the client with mock functions for demonstration
# In production, pass actual SPARQL query/update functions
client = JenaClient(
    dataset="tenders",
    sparql_query_fn=lambda query, dataset: {"boolean": True},
    sparql_update_fn=lambda update, dataset: print(f"Executing update on {dataset}")
)

# 1. Find a tender by reference
tender_iri = client.find_tender_by_ref("AO_2026_001")
if tender_iri:
    print(f"Found Tender: {tender_iri}")

# 2. Check quality gates
if client.check_tender_has_spec(tender_iri):
    print("Tender has specifications.")

# 3. Insert triples
success = client.insert_triples("<http://ex.org/s> <http://ex.org/p> 'value' .")
print(f"Insert success: {success}")
