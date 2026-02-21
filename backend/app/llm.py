import httpx
import logging
from typing import Optional
from .config import settings

logger = logging.getLogger(__name__)

# Basic crisis keywords detection as requested
CRISIS_KEYWORDS = [
    "suicide",
    "kill myself",
    "end my life",
    "hurt myself",
    "want to die"
]

CRISIS_RESPONSE = (
    "I'm so sorry you're feeling this way, but I'm an AI and cannot provide the help you "
    "need right now. Please know that you are not alone. Please reach out to a local emergency "
    "service, a crisis hotline, or a trusted medical professional immediately. In many regions, "
    "dialing 988 or your local emergency number will connect you with people who can support you."
)

SYSTEM_PROMPT = (
    "You are a compassionate CBT-based AI therapist. "
    "You provide supportive, non-diagnostic, non-medical guidance. "
    "If user expresses self-harm ideation, respond empathetically and recommend professional help."
)


def contains_crisis_keywords(message: str) -> bool:
    """
    Check if the user message contains any hardcoded crisis keywords.
    """
    msg_lower = message.lower()
    return any(keyword in msg_lower for keyword in CRISIS_KEYWORDS)


async def generate_therapeutic_response(user_message: str) -> str:
    """
    1. Check for crisis
    2. Construct prompt
    3. Call local llama-server
    4. Return response
    """
    # 1. Safety first: simple keyword detection before LLM call
    if contains_crisis_keywords(user_message):
        return CRISIS_RESPONSE

    # 2. Construct requestpayload
    # This payload format assumes compatibility with llama.cpp's server 
    # (specifically the /completion endpoint or similar OAI compatible endpoint). 
    # For a generic /completion endpoint, we format it as a prompt string.
    
    prompt = f"System: {SYSTEM_PROMPT}\nUser: {user_message}\nTherapist:"
    
    payload = {
        "prompt": prompt,
        "temperature": settings.LLM_TEMPERATURE,
        "n_predict": settings.LLM_MAX_TOKENS,
        "stop": ["User:", "\nSystem:"]
    }

    # 3. Call local model
    try:
        # We use a short timeout assuming it's running locally, but LLMs can be slow
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(settings.LLAMA_SERVER_URL, json=payload)
            response.raise_for_status()
            
            data = response.json()
            # llama.cpp server typically returns the generated text in "content" or "text" depending on exact endpoint
            # checking common structures
            reply = data.get("content", "")
            if not reply:
                reply = data.get("text", "") # fallback
                
            if not reply:
               # Try OpenAI chat completion format if llama-server was started with --chat
               if "choices" in data and len(data["choices"]) > 0:
                   choice = data["choices"][0]
                   if "message" in choice and "content" in choice["message"]:
                        reply = choice["message"]["content"]
                   elif "text" in choice:
                        reply = choice["text"]
                        
            if not reply:
                # If we still don't have a reply, return the raw data block for debugging
                reply = f"[Debug fallback] LLM returned unrecognized format: {str(data)}"
                
            return reply.strip()
            
    except httpx.RequestError as e:
        logger.error(f"Error communicating with local LLM server: {e}")
        return f"I'm having trouble connecting to my thought algorithms right now. (Error: {str(e)})"
    except Exception as e:
        logger.error(f"Unexpected error in LLM generation: {e}")
        return f"An unexpected error occurred while processing your message. (Error: {str(e)})"
