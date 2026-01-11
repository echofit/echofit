FROM python:3.11-slim

WORKDIR /app

# Context is root, so copy only what we need
COPY requirements.mcp.txt ./requirements.txt
COPY setup.py ./
COPY food_agent/sdk/ ./food_agent/sdk/
COPY food_agent/mcp/ ./food_agent/mcp/
COPY food_agent/mcp_service/ ./food_agent/mcp_service/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install .

EXPOSE 8080

# Run the MCP service
CMD ["uvicorn", "food_agent.mcp_service.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
