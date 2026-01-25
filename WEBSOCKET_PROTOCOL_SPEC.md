# concierge.v1 WebSocket Protocol

 - Endpoint: wss://<ws_interface_defaults_to_0.0.0.0>:<ws_port_defaults_to_8765>?token={token}
 - Protocol: concierge.v1

## Authentication

  - Token obtained from GET /concierge/api/v1/ws/token
  - Valid for 30 seconds
  - Single-use (nonce-based)

## E2E Encryption

TLS, using the cert and key as the HTTPS service

## Message Formats

### CLI Mode (text)

#### Server -> Client

Process output

```json
{"type": "stdout", "data": "text"}
```

Process status

```json
{"type": "status", "status": "success|error|running"}
```

Connection success
```json
{"type": "connected"}
```

#### Client -> Server

Raw text frame
```text
[Any UTF-8 character]
```

Control sequences
```json
{"type": "control", "char": "C|D|Z"}
```

### JPEG Stream Mode (binary)

#### Server -> Client

Binary frame with header
```text
[4 bytes: type length][type string][4 bytes: data length][data]
```

#### Client -> Server
Not applicable (no stdin for jpeg_stream)
