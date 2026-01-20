# System Stability Post-Mortem

## The Core Problem: Synchronous Blocking in an Asynchronous Server

The fundamental issue preventing your HFT bot from launching and shutting down correctly was a **concurrency conflict** between `FastAPI` (Uvicorn) and the `market_maker.py` trading logic.

### 1. The "Gil" Starvation (Startup Hang)
FastAPI relies on Python's `asyncio` event loop to handle web requests (like `/docs` and WebSockets).
*   **What happened:** The trading bot's main loop (`while True`) was initially running as an `async` task within that *same* event loop.
*   **The Conflict:** Even though we wrapped network calls in `to_thread`, the *glue logic* (processing JSON, iterating arrays, math) was CPU-bound enough—or accidentally touched a blocking call—that it "hogged" the event loop.
*   **Result:** Uvicorn couldn't get a "tick" in to accept HTTP connections, causing `/docs` to time out (Connection Refused).

### 2. The "Zombie" Shutdown (Ctrl+C Failure)
When you pressed `Ctrl+C`, Python sent a `SIGINT` to the main process.
*   **The Mechanism:** Uvicorn catches this signal and tries to "cancel" all running tasks.
*   **The Failure:** The Bot Task was running an infinite loop. Unless that loop *explicitly* checks for cancellation *every few milliseconds* and yields control, it ignores the cancel request.
*   **Result:** The server process "hung" because it was waiting for the Bot Task to die, but the Bot Task was too busy running to notice it was supposed to die. This left "zombie" python processes holding onto ports 8000/8001.

### 3. The "Reload" Interference
You were running `uvicorn --reload`.
*   **The Issue:** The auto-reloader runs your app in a *subprocess*. When you hit `Ctrl+C`, you kill the *watcher*, but sometimes the *child process* (the actual bot) gets detached and keeps running in the background.
*   **Result:** This is why you saw "Address already in use" errors. The previous run was ghosting in the background, unaware it should have stopped.

### 4. The Solution Implemented (Architecture)
To fix this permanently, we moved from **Asyncio Cooperation** to **OS Thread Isolation**.
*   **Daemon Thread:** The bot now runs in a `threading.Thread(daemon=True)`.
*   **Behavior:** A "Daemon" thread is a second-class citizen. If the Main Thread (Uvicorn) exits, the OS *immediately and forcibly* kills the Daemon thread. It doesn't ask permission.
*   **Outcome:** `Ctrl+C` kills Uvicorn -> OS kills Bot. No zombies. No hanging.

Your code is now architected correctly to handle these two hostile loops (Server vs. HFT) side-by-side.
