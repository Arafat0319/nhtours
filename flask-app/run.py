from app import create_app, db
from app.models import User, Trip, City, Client, ItineraryItem, Payment

app = create_app()

@app.shell_context_processor
def make_shell_context():
    return {
        'db': db, 
        'User': User, 
        'Trip': Trip, 
        'City': City, 
        'Client': Client,
        'ItineraryItem': ItineraryItem,
        'Payment': Payment
    }

if __name__ == '__main__':
    app.run(debug=True)
