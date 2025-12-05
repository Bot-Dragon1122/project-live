from dotenv import load_dotenv
load_dotenv()

from app import app
import routes

if __name__ == "__main__":
    app.run(debug=True)
