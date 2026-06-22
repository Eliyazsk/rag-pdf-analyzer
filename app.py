import os
import shutil
import json
from flask import Flask, render_template, request, jsonify
from pypdf import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings, ChatNVIDIA
try:
    from langchain_community.vectorstores import FAISS
except Exception as e:
    print(f"FAISS import failed: {e}. Using MockFAISS fallback.")
    class FAISS:
        def __init__(self, embedding_function, index=None):
            self.embedding_function = embedding_function
            self.index = index or []

        @classmethod
        def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
            instance = cls(embedding)
            instance.add_texts(texts, metadatas)
            return instance

        def add_texts(self, texts, metadatas=None, **kwargs):
            embeddings = self.embedding_function.embed_documents(texts)
            for i, text in enumerate(texts):
                metadata = metadatas[i] if metadatas else {}
                self.index.append({
                    "text": text,
                    "metadata": metadata,
                    "embedding": embeddings[i]
                })

        def save_local(self, folder_path, **kwargs):
            import pickle
            os.makedirs(folder_path, exist_ok=True)
            data_path = os.path.join(folder_path, "index.pkl")
            with open(data_path, "wb") as f:
                pickle.dump(self.index, f)

        @classmethod
        def load_local(cls, folder_path, embeddings, allow_dangerous_deserialization=False, **kwargs):
            import pickle
            instance = cls(embeddings)
            data_path = os.path.join(folder_path, "index.pkl")
            if os.path.exists(data_path):
                with open(data_path, "rb") as f:
                    instance.index = pickle.load(f)
            else:
                raise FileNotFoundError(f"No index file found at {data_path}")
            return instance

        def similarity_search(self, query, k=4, **kwargs):
            import math
            query_embedding = self.embedding_function.embed_query(query)
            
            results = []
            for item in self.index:
                emb = item["embedding"]
                dot_product = sum(a * b for a, b in zip(query_embedding, emb))
                norm_a = math.sqrt(sum(a * a for a in query_embedding))
                norm_b = math.sqrt(sum(b * b for b in emb))
                similarity = dot_product / (norm_a * norm_b) if norm_a and norm_b else 0
                results.append((similarity, item))
                
            results.sort(key=lambda x: x[0], reverse=True)
            
            from langchain_core.documents import Document
            docs = []
            for sim, item in results[:k]:
                docs.append(Document(
                    page_content=item["text"],
                    metadata=item["metadata"]
                ))
            return docs

from langchain.chains.question_answering import load_qa_chain
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

app = Flask(__name__)

# Directory setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'):
    # Vercel has read-only file system, only /tmp is writable
    UPLOAD_FOLDER = '/tmp/uploads'
    FAISS_INDEX_PATH = '/tmp/faiss_index'
    SOURCES_JSON_PATH = '/tmp/sources.json'
else:
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    FAISS_INDEX_PATH = os.path.join(BASE_DIR, 'faiss_index')
    SOURCES_JSON_PATH = os.path.join(BASE_DIR, 'sources.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Delete existing index on fresh startup to ensure clean session
if os.path.exists(FAISS_INDEX_PATH):
    try:
        shutil.rmtree(FAISS_INDEX_PATH)
    except Exception:
        pass
if os.path.exists(SOURCES_JSON_PATH):
    try:
        os.remove(SOURCES_JSON_PATH)
    except Exception:
        pass
# Clear upload folder on startup to start fresh
for filename in os.listdir(UPLOAD_FOLDER):
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    try:
        if os.path.isfile(file_path) or os.path.islink(file_path):
            os.unlink(file_path)
        elif os.path.isdir(file_path):
            shutil.rmtree(file_path)
    except Exception:
        pass

def get_api_key(request_data=None):
    """Retrieves the NVIDIA API Key from input payload or environment."""
    key = None
    if request_data:
        key = request_data.get('api_key')
    if not key and request.form:
        key = request.form.get('api_key')
    if not key:
        key = os.getenv("NVIDIA_API_KEY")
    return key

def get_embeddings_model(api_key):
    """Initializes NVIDIA Embeddings using the verified nv-embedqa-e5-v5 model."""
    return NVIDIAEmbeddings(model="nvidia/nv-embedqa-e5-v5", nvidia_api_key=api_key)

def get_conversational_chain(api_key):
    """Creates a conversational prompt QA chain using ChatNVIDIA Llama 3.3 70B model."""
    prompt_template = """
    You are an intelligent, friendly, and natural AI assistant (like ChatGPT). 
    Your goal is to answer the user's question accurately using only the provided context from their uploaded PDF documents.
    
    Instructions:
    1. Base your answer strictly on the provided Context.
    2. Write in a smooth, engaging, and natural conversational tone. Avoid robotic phrases like "Based on the provided context..." or "The context states...". Talk to the user directly.
    3. If the answer cannot be found or inferred from the context, politely respond that you couldn't find that specific detail in the active documents, and ask if there's anything else you can help with.
    4. Structure your response clearly (using bullet points or formatting) to make it highly readable and elegant.

    Context:
    {context}
    
    Question:
    {question}
    
    Answer:
    """
    model = ChatNVIDIA(model="meta/llama-3.3-70b-instruct", nvidia_api_key=api_key, temperature=0.5)
    prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
    chain = load_qa_chain(model, chain_type="stuff", prompt=prompt)
    return chain

def extract_pdf_pages(file_path):
    """Reads a PDF file and returns a list of dictionaries with text and page numbers."""
    pages = []
    pdf_reader = PdfReader(file_path)
    for i, page in enumerate(pdf_reader.pages):
        text = page.extract_text()
        if text:
            pages.append({
                "text": text,
                "page": i + 1
            })
    return pages

def rebuild_faiss_index(api_key):
    """Rebuilds the FAISS index from all files currently stored in UPLOAD_FOLDER in batches."""
    if os.path.exists(FAISS_INDEX_PATH):
        try:
            shutil.rmtree(FAISS_INDEX_PATH)
        except Exception:
            pass

    all_texts = []
    all_metadatas = []
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)
    
    for filename in os.listdir(UPLOAD_FOLDER):
        if filename.endswith(".pdf"):
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            pages = extract_pdf_pages(file_path)
            
            for page in pages:
                chunks = text_splitter.split_text(page["text"])
                for chunk in chunks:
                    all_texts.append(chunk)
                    all_metadatas.append({
                        "source": filename,
                        "page": page["page"]
                    })
                    
    if all_texts:
        embeddings = get_embeddings_model(api_key)
        batch_size = 40  # Process chunks in small batches to avoid network timeout and API limits
        vector_store = None
        for i in range(0, len(all_texts), batch_size):
            batch_texts = all_texts[i:i + batch_size]
            batch_metadatas = all_metadatas[i:i + batch_size]
            if vector_store:
                vector_store.add_texts(batch_texts, metadatas=batch_metadatas)
            else:
                vector_store = FAISS.from_texts(batch_texts, embedding=embeddings, metadatas=batch_metadatas)
            vector_store.save_local(FAISS_INDEX_PATH)


def is_chitchat(question):
    """Detects if a user query is general chitchat or greetings."""
    q = question.lower().strip().rstrip('?!.')
    chitchat_phrases = {
        "hi", "hello", "hey", "greetings", "good morning", "good afternoon", "good evening",
        "how are you", "how's it going", "how are you doing", "how do you do",
        "who are you", "what is your name", "what are you", "who made you",
        "what can you do", "help", "what is this app", "hi how are you"
    }
    if q in chitchat_phrases:
        return True
    # Check prefixes
    for prefix in ["hi ", "hello ", "hey ", "good morning ", "good afternoon ", "good evening "]:
        if q.startswith(prefix):
            return True
    return False

@app.route('/')
def home():
    """Renders the main NotebookLM index template."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handles multiple file uploads, extracts page texts, chunks them, and adds to FAISS index."""
    api_key = get_api_key()
    if not api_key:
        return jsonify({"error": "NVIDIA API Key is missing. Please provide it in the sidebar settings."}), 400

    if 'files' not in request.files:
        return jsonify({"error": "No files uploaded."}), 400

    uploaded_files = request.files.getlist('files')
    if not uploaded_files or uploaded_files[0].filename == '':
        return jsonify({"error": "No selected files."}), 400

    try:
        new_files_added = False
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)
        
        for file in uploaded_files:
            filename = file.filename
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            
            # Skip if file already exists on server disk
            if os.path.exists(file_path):
                continue
                
            file.save(file_path)
            new_files_added = True
            
            # Extract pages
            pages = extract_pdf_pages(file_path)
            if not pages:
                continue
                
            texts = []
            metadatas = []
            
            for page in pages:
                chunks = text_splitter.split_text(page["text"])
                for chunk in chunks:
                    texts.append(chunk)
                    metadatas.append({
                        "source": filename,
                        "page": page["page"]
                    })
            
            if texts:
                embeddings = get_embeddings_model(api_key)
                batch_size = 40
                vector_store = None
                
                if os.path.exists(FAISS_INDEX_PATH):
                    vector_store = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
                
                for i in range(0, len(texts), batch_size):
                    batch_texts = texts[i:i + batch_size]
                    batch_metadatas = metadatas[i:i + batch_size]
                    
                    if vector_store:
                        vector_store.add_texts(batch_texts, metadatas=batch_metadatas)
                    else:
                        vector_store = FAISS.from_texts(batch_texts, embedding=embeddings, metadatas=batch_metadatas)
                    
                    # Save incremental progress
                    vector_store.save_local(FAISS_INDEX_PATH)

                    
        return jsonify({"message": "Successfully indexed uploaded documents."}), 200

    except Exception as e:
        return jsonify({"error": f"An error occurred during file ingestion: {str(e)}"}), 500

@app.route('/delete_source', methods=['POST'])
def delete_source():
    """Deletes a source PDF and rebuilds the FAISS index from remaining files."""
    data = request.get_json() or {}
    filename = data.get('filename')
    api_key = get_api_key(data)

    if not filename:
        return jsonify({"error": "Filename is required."}), 400
    if not api_key:
        return jsonify({"error": "NVIDIA API Key is required."}), 400

    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            # Rebuild index from all remaining uploaded documents
            rebuild_faiss_index(api_key)
            return jsonify({"message": f"Successfully deleted source '{filename}'."}), 200
        except Exception as e:
            return jsonify({"error": f"Failed to delete source: {str(e)}"}), 500
    else:
        return jsonify({"error": f"File '{filename}' not found."}), 404

@app.route('/summary', methods=['POST'])
def get_summary():
    """Generates a structured summarization of a specific PDF source using ChatNVIDIA Llama."""
    data = request.get_json() or {}
    filename = data.get('filename')
    api_key = get_api_key(data)

    if not filename:
        return jsonify({"error": "Filename is required."}), 400
    if not api_key:
        return jsonify({"error": "NVIDIA API Key is missing."}), 400

    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": f"File '{filename}' does not exist on the server."}), 404

    try:
        pages = extract_pdf_pages(file_path)
        # Combine text from up to first 5 pages to make a fast summary
        summary_text = "\n".join([page["text"] for page in pages[:5]])
        
        model = ChatNVIDIA(model="meta/llama-3.3-70b-instruct", nvidia_api_key=api_key, temperature=0.3)
        prompt = (
            f"You are a helpful assistant. Provide a structured, concise summary of the document '{filename}'. "
            "Include key topics, primary goals, and target audience if applicable. Use markdown bullet points.\n\n"
            f"Document Text:\n{summary_text[:12000]}"
        )
        response = model.invoke(prompt)
        return jsonify({"summary": response.content}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to generate summary: {str(e)}"}), 500

@app.route('/briefing', methods=['POST'])
def generate_briefing():
    """Generates a Notebook Study Guide combining all active sources."""
    data = request.get_json() or {}
    active_sources = data.get('active_sources', [])
    api_key = get_api_key(data)

    if not active_sources:
        return jsonify({"error": "Please select at least one active source."}), 400
    if not api_key:
        return jsonify({"error": "NVIDIA API Key is missing."}), 400

    try:
        combined_text = ""
        for filename in active_sources:
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(file_path):
                pages = extract_pdf_pages(file_path)
                # Take first 3 pages of each active source to stay within context
                combined_text += f"\n--- Source Document: {filename} ---\n"
                combined_text += "\n".join([p["text"] for p in pages[:3]]) + "\n"

        model = ChatNVIDIA(model="meta/llama-3.3-70b-instruct", nvidia_api_key=api_key, temperature=0.5)
        prompt = (
            "You are an expert tutor. Create a comprehensive, beautiful Markdown Study Guide based on the following text context from the sources.\n"
            "Format the guide with the following sections:\n"
            "# Study Guide: [Title based on content]\n"
            "## Executive Briefing\n"
            "[Provide a high-level summary of the concepts]\n"
            "## Key Glossary & Terms\n"
            "[List important terms and definitions]\n"
            "## Focus Q&A\n"
            "[Provide 3-4 study questions and answers]\n\n"
            f"Source Documents Content:\n{combined_text[:18000]}"
        )
        response = model.invoke(prompt)
        return jsonify({"briefing": response.content}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to generate briefing document: {str(e)}"}), 500

@app.route('/ask', methods=['POST'])
def ask_question():
    """Performs similarity search, filters chunks by active sources list, and returns answers with citations."""
    data = request.get_json() or {}
    question = data.get('question')
    active_sources = data.get('active_sources', [])

    if not question:
        return jsonify({"error": "No question provided."}), 400

    api_key = get_api_key(data)
    if not api_key:
        return jsonify({"error": "NVIDIA API Key is missing."}), 400

    # Handle chitchat conversationally without context
    if is_chitchat(question):
        try:
            model = ChatNVIDIA(model="meta/llama-3.3-70b-instruct", nvidia_api_key=api_key, temperature=0.7)
            prompt = (
                "You are an intelligent, friendly AI assistant. Answer the user's greeting or chitchat naturally. "
                "Mention that if they upload PDF documents in the sidebar, you can answer specific questions about them. "
                f"User greeting: {question}"
            )
            response = model.invoke(prompt)
            return jsonify({"answer": response.content, "citations": []}), 200
        except Exception as e:
            return jsonify({"error": f"Model connection error: {str(e)}"}), 500

    # Ensure index exists for document queries
    if not os.path.exists(FAISS_INDEX_PATH):
        return jsonify({"error": "No documents found. Please upload and process PDF documents first."}), 400

    if not active_sources:
        return jsonify({"answer": "You don't have any sources selected in the left panel. Please check at least one source checkbox to chat about its contents.", "citations": []}), 200

    try:
        embeddings = get_embeddings_model(api_key)
        new_db = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
        
        # Search for top matches (fetch k=25 to filter by active sources in python)
        results = new_db.similarity_search(question, k=25)
        
        # Filter chunks by active source files list
        filtered_docs = [doc for doc in results if doc.metadata.get("source") in active_sources]
        
        # Take the top 4 matched chunks
        docs_to_use = filtered_docs[:4]

        if not docs_to_use:
            return jsonify({
                "answer": "I couldn't find any relevant sections in your currently checked sources. Try checking other files in the sidebar or adjusting your question.",
                "citations": []
            }), 200

        # Build citations list
        citations = []
        for doc in docs_to_use:
            citation_item = {
                "source": doc.metadata.get("source"),
                "page": doc.metadata.get("page")
            }
            if citation_item not in citations:
                citations.append(citation_item)

        # Execute conversational prompt QA chain
        chain = get_conversational_chain(api_key)
        response = chain(
            {"input_documents": docs_to_use, "question": question},
            return_only_outputs=True
        )
        
        return jsonify({
            "answer": response["output_text"],
            "citations": citations
        }), 200

    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    # Start web server on port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
