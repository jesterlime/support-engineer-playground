class DuplicatePaymentError(Exception):
    def __init__(self, payment_id, correlation_id):
        self.message = 'Idempotency key already exists'
        self.payment_id = payment_id
        self.correlation_id = correlation_id

class NotFoundError(Exception):
    def __init__(self):
        self.message = 'Payment not found'