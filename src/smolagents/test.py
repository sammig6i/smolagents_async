import asyncio

from smolagents.agents import CodeAgent
from smolagents.models import AzureOpenAIServerModel
from smolagents.tools import Tool

class AsyncCalculatorTool(Tool):
    name = "async_calculator"
    description = "A tool that performs mathematical calculations with a simulated delay"
    inputs = {
        "expression": {
            "type": "string",
            "description": "The mathematical expression to evaluate"
        }
    }
    output_type = "number"

    async def forward(self, expression: str) -> float:
        # Simulate some async work
        await asyncio.sleep(1)
        return eval(expression)

async def main():
    # Initialize the Azure OpenAI model
    model = AzureOpenAIServerModel(
        "gpt-4o-mini",
        api_version="2024-02-15-preview",
        azure_endpoint="https://openai-swedencentral-respeak.openai.azure.com/",  # You'll provide this
        api_key="772bcecff1574db8add413353e4933c1",  # You'll provide this
    )
    
    # Create calculator tool instance
    calculator = AsyncCalculatorTool()
    
    # Create the agent with the model and tool
    agent = CodeAgent(tools=[calculator], model=model)
    
    # Basic async execution
    result = await agent.run("Calculate 2 power 3.7384 using the async calculator")
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(main())