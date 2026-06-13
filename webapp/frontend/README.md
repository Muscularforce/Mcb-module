# MCB Frontend Dashboard

A stunning, premium web interface for the MCB application, built with React, TypeScript, and Vite.

## Features
- 🌙 **Beautiful Dark Mode**: Uses deep slate tones and vibrant accents.
- 🧊 **Glassmorphism**: Elegant translucent panels with smooth hover effects.
- ⚡ **Lightning Fast**: Powered by Vite and React.
- 📱 **Responsive**: Grid layout adapts seamlessly to any screen size.
- ✨ **Micro-animations**: Subtle interactions that make the UI feel alive.
- 🔌 **API Integration**: Fetches data from the FastAPI backend at `http://localhost:8000/api/entries`.

## Getting Started

Because the initial setup automated some steps, you can run this project locally right away.

1. Navigate to the frontend directory:
   ```bash
   cd "c:/Users/Jovan Fernandes/OneDrive/Documents/mcb  int/webapp/frontend"
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```

4. Open your browser and navigate to the local URL provided by Vite (usually `http://localhost:5173`).

### Backend Connectivity
The app attempts to fetch from `http://localhost:8000/api/entries`. If the FastAPI server is not running, it gracefully falls back to mock data so you can still preview the gorgeous UI.
