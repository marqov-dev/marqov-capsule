# FIXTURE: contains synthetic credential for testing CapsuleRedactor
# DO NOT use real credentials — this token is fabricated
from qiskit_ibm_runtime import QiskitRuntimeService

token = "ibmq_fake_token_abcdef1234567890abcdef1234567890abcdef"
service = QiskitRuntimeService(token=token)
