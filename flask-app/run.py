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
    import os
    # Windows Hyper-V 常保留 4927–5026，导致默认 5000 无法绑定
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='127.0.0.1', port=port)
