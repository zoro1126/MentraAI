from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas, crud, llm
from ..database import get_db

router = APIRouter(
    tags=["Chat"],
    responses={404: {"description": "Not found"}},
)


@router.post("/chat", response_model=schemas.ChatResponse)
async def chat_interaction(request: schemas.ChatRequest, db: Session = Depends(get_db)):
    """
    Accept user message, pass to local llama, return therapeutic resp, 
    and save session history in DB.
    """
    user_message = request.message
    
    # Send to AI layer (handles prompt assembly and safety checks)
    ai_response = await llm.generate_therapeutic_response(user_message)
    
    # Save the interaction to the database
    crud.create_chat_session(
        db=db,
        user_id=request.user_id,
        user_message=user_message,
        ai_response=ai_response
    )
    
    return schemas.ChatResponse(reply=ai_response)
