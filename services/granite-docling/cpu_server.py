"""
Granite-Docling CPU Server
==========================
OpenAI-compatible API server using Transformers backend (CPU mode).
Slower than vLLM but works without GPU.
"""

import os
import base64
import asyncio
from io import BytesIO
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Lazy load heavy imports
model = None
processor = None

app = FastAPI(
    title="Granite-Docling API (CPU)",
    description="OpenAI-compatible API for Granite-Docling-258M (CPU mode)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# OpenAI-Compatible Request/Response Models
# ============================================================================

class ImageUrl(BaseModel):
    url: str


class ContentPart(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[ImageUrl] = None


class Message(BaseModel):
    role: str
    content: list[ContentPart] | str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    max_tokens: int = Field(default=8192)
    temperature: float = Field(default=0.0)
    stream: bool = Field(default=False)


class Choice(BaseModel):
    index: int
    message: dict
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


# ============================================================================
# Model Loading
# ============================================================================

def load_model():
    """Load Granite-Docling model and processor."""
    global model, processor

    if model is not None:
        return

    print("Loading Granite-Docling-258M model...")

    from transformers import AutoModelForVision2Seq, AutoProcessor
    import torch

    model_name = os.getenv("MODEL_NAME", "ibm-granite/granite-docling-258M")

    # Determine device
    if torch.cuda.is_available():
        device = "cuda"
        dtype = torch.float16
    else:
        device = "cpu"
        dtype = torch.float32

    print(f"Using device: {device}, dtype: {dtype}")

    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModelForVision2Seq.from_pretrained(
        model_name,
        torch_dtype=dtype,
        device_map=device
    )

    print("Model loaded successfully!")


# ============================================================================
# Endpoints
# ============================================================================

@app.on_event("startup")
async def startup():
    """Load model on startup."""
    load_model()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy" if model is not None else "loading",
        "model": os.getenv("MODEL_NAME", "ibm-granite/granite-docling-258M"),
        "backend": "transformers-cpu"
    }


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """List available models (OpenAI-compatible)."""
    return ModelsResponse(
        data=[
            ModelInfo(
                id=os.getenv("MODEL_NAME", "ibm-granite/granite-docling-258M"),
                created=int(datetime.now().timestamp()),
                owned_by="ibm-granite"
            )
        ]
    )


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI-compatible chat completions endpoint.
    Supports vision inputs for document processing.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    from PIL import Image
    import torch

    # Extract image and text from messages
    image = None
    prompt = ""

    for message in request.messages:
        if isinstance(message.content, str):
            prompt += message.content
        elif isinstance(message.content, list):
            for part in message.content:
                if part.type == "text" and part.text:
                    prompt += part.text
                elif part.type == "image_url" and part.image_url:
                    # Decode base64 image
                    url = part.image_url.url
                    if url.startswith("data:image"):
                        # Extract base64 data
                        header, data = url.split(",", 1)
                        image_data = base64.b64decode(data)
                        image = Image.open(BytesIO(image_data)).convert("RGB")
                    else:
                        # URL - fetch image
                        import httpx
                        response = httpx.get(url)
                        image = Image.open(BytesIO(response.content)).convert("RGB")

    if image is None:
        raise HTTPException(status_code=400, detail="No image provided")

    # Process with model
    try:
        inputs = processor(
            images=image,
            text=prompt,
            return_tensors="pt"
        )

        # Move to device
        device = next(model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        # Generate
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=request.max_tokens,
                do_sample=request.temperature > 0,
                temperature=request.temperature if request.temperature > 0 else None,
            )

        # Decode
        generated_text = processor.decode(outputs[0], skip_special_tokens=True)

        # Remove prompt from output if present
        if prompt in generated_text:
            generated_text = generated_text.replace(prompt, "").strip()

        response = ChatCompletionResponse(
            id=f"chatcmpl-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            created=int(datetime.now().timestamp()),
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message={"role": "assistant", "content": generated_text},
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=len(inputs.get("input_ids", [[]])[0]),
                completion_tokens=len(outputs[0]),
                total_tokens=len(inputs.get("input_ids", [[]])[0]) + len(outputs[0])
            )
        )

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
