import os
import openai
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

def lambda_handler(event, context):
    # Set the API key
    openai.api_key = ""
    
    # Get the prompt from the event data
    prompt = event.get('prompt', '')

    # Log the received prompt
    logging.info("Received prompt: %s", prompt)

    try:
        # Create a chat completion
        chat_completion = openai.ChatCompletion.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="gpt-3.5-turbo",
        )

        # Log the response
        response = chat_completion['choices'][0]['message']['content']
        logging.info("Received response: %s", response)

        # Return the output of the chat completion
        return response

    except Exception as e:
        # Log any errors that occur during execution
        logging.error("An error occurred: %s", e)
        # Return a generic error message
        return "An error occurred. Please try again later."
