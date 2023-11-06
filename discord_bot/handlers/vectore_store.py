import pinecone, uuid

INDEX_NAME = "discord-bot-context"
ENVIRONMENT = "us-west4-gcp-free"
# This comes from the model we're using for embeddings, ada-002
DIMENSIONS = 1536
RETRIEVAL_LIMIT = 9

class VectorStore:
    def __init__(self, pinecone_api_key):
        self.pinecone_api_key = pinecone_api_key
        self.index = None
        self.index_name = INDEX_NAME

    def initialize_pinecone(self):
        pinecone.init(api_key=self.pinecone_api_key, environment=ENVIRONMENT)
        if self.index_name not in pinecone.list_indexes():
            pinecone.create_index(name=self.index_name, metric="cosine", dimension=DIMENSIONS)
        self.index = pinecone.Index(self.index_name)

    def store_additional_data(self, vector, summary):
        unique_id = str(uuid.uuid4())  # Generate a unique ID
        #print(f"Storing additional data: {summary} with uuid {unique_id} in namespace {namespace}")
        self.index.upsert(vectors=[{
            'id': unique_id,
            'values': vector,
            'metadata': {'summary': summary}
        }])

    def fetch_context(self, query_vector):
        try:
            #print(f"index is...: {self.index}")
            results = self.index.query(
                top_k=RETRIEVAL_LIMIT,  # Number of closest vectors to retrieve
                include_values=False,  # Whether to include the vectors themselves in the response
                include_metadata=True,  # Whether to include any metadata stored alongside vectors
                vector=query_vector     # The query vector
            )
            #print(f"index query results: {results}")
            # Extract the metadata from the closest matches
            if results and 'matches' in results and len(results['matches']) > 0:
                closest_matches = [match['metadata'] for match in results['matches']]
            else:
                print("No matches found.")
                closest_matches = []

            return closest_matches
        except Exception as e:
            print(f"An error occurred: {e}")
            return None


    async def close(self):
        pinecone.deinit()
