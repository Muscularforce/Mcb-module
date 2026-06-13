# MCB Backend

This is the FastAPI backend for the MCB application. It provides a RESTful API and uses SQLite for data storage.

## Features
- FastAPI application
- SQLite database with SQLAlchemy ORM
- Combined `Entry` model for DiaryEntries, Worksheets, and Announcements
- CORS configured for frontend at `http://localhost:5173`

## Setup Instructions

1. **Navigate to the backend directory**:
   ```bash
   cd "c:/Users/Jovan Fernandes/OneDrive/Documents/mcb  int/webapp/backend"
   ```

2. **Create and activate a virtual environment (optional but recommended)**:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install the dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the development server**:
   ```bash
   uvicorn main:app --reload
   ```

## API Documentation
Once the server is running, you can view the interactive API documentation (Swagger UI) at:
- http://localhost:8000/docs
