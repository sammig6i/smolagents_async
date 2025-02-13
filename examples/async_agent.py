import math
import asyncio
import os

from dotenv import load_dotenv

from smolagents import CodeAgent
from smolagents.models import AzureOpenAIServerModel
from smolagents import Tool


load_dotenv()


class CalculatePowerTool(Tool):
    name = "calculate_power"
    description = "Calculates the power of a number asynchronously."
    inputs = {
        "base": {"type": "number", "description": "The base number."},
        "exponent": {"type": "number", "description": "The exponent number."}
    }
    output_type = "number"

    async def forward(self, base: float, exponent: float) -> float:
        # Simulate some async work
        await asyncio.sleep(0.1)
        return math.pow(base, exponent)


async def main():
    # Initialize the Azure OpenAI model
    model = AzureOpenAIServerModel(
        "gpt-4o-mini",
        api_version="2024-02-15-preview",
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    )
    
    # Create the agent with the calculation tool
    tools = [
        CalculatePowerTool()
    ]
    agent = CodeAgent(tools=tools, model=model)
    
    # Basic async execution
    result = await agent.run("What is the result of 2 power 3.7384?")
    print("Result:", result)
    

if __name__ == "__main__":
    asyncio.run(main())