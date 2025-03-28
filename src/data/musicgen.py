"""
Contains functions for creating generative features of songs. 

Inspired by work in: https://arxiv.org/pdf/2107.05677

We adapt their method to use with a newer model, MusicGen.
"""

import autorootcwd

import torch
import torch.nn.functional as F
import torchaudio
from torchaudio.transforms import Resample

from audiocraft.models import MusicGen
from audiocraft.modules.conditioners import ConditioningAttributes
from audiocraft.modules.transformer import create_sin_embedding

from src.utils import get_torch_device

def get_musicgen_model(model_size: str, device: str = "cuda"):
    """
    Returns a pretrained MusicGen model.

    Args:
    - model_size (str): The size of the model to load. Either 'small' or 'large'.

    Returns:
    - model (MusicGen): The pretrained model.
    """
    assert model_size in ["small", "large"], "Model size must be 'small' or 'large'."
    model = MusicGen.get_pretrained("facebook/musicgen-" + model_size, device=device)
    return model

def get_wav(filename: str, dir = "./data/processed/"):
    """
    Loads a wav file from the given directory. Resamples the audio to 32kHz if the model is not None.

    Args:
    - filename (str): The name of the file to load.
    - dir (str): The directory to load the file from.

    Returns:
    - wav (torch.Tensor): The audio waveform.
    """
    wav, sr = torchaudio.load(f"{dir}/audio/{filename}.mp3")
    new_sr = 32000
    resampler = Resample(orig_freq=sr, new_freq=new_sr)
    wav = resampler(wav)
    return wav

def resample_hidden_states(
    hidden_states: torch.Tensor,
    model,
    desired_frame_length: float
) -> torch.Tensor:
    """
    Resample hidden state tensor to a new temporal resolution given a desired frame length.
    
    Args:
        hidden_states (torch.Tensor): Tensor of shape [B, T, D] representing hidden states.
        model: The MusicGen model (used to obtain model.compression_model.frame_rate if input_duration is not provided).
        desired_frame_length (float): Desired time interval between frames (in seconds). 
            For example, 4096/44100 (~0.093 s) yields ~10-11 frames per second.
    
    Returns:
        torch.Tensor: Resampled hidden states of shape [B, new_T, D],
            where new_T = round(input_duration / desired_frame_length).
    """
    B, T, D = hidden_states.shape

    current_frame_rate = model.compression_model.frame_rate
    input_duration = T / current_frame_rate  # in seconds

    # Compute the new number of time steps so that each represents the desired frame length.
    new_T = int(round(input_duration / desired_frame_length))

    # Permute to [B, D, T] because F.interpolate operates on the last dimension as time.
    hidden_states_perm = hidden_states.permute(0, 2, 1)
    
    # Use linear interpolation along the time dimension.
    resampled = F.interpolate(hidden_states_perm, size=new_T, mode='linear', align_corners=False)
    
    # Permute back to [B, new_T, D]
    resampled = resampled.permute(0, 2, 1)
    
    return resampled

def get_intermediate_hidden_state(model, prompt_tokens, text="a song", layer_index=None):
    """
    Given a MusicGen model and a token tensor (shape [B, K, S]),
    returns the LM transformer hidden state at a specified intermediate layer.
    
    Args:
        model: A pretrained MusicGen model (loaded via MusicGen.get_pretrained).
        prompt_tokens (torch.Tensor): Token tensor from the compression model of shape [B, K, S],
            where K is the number of codebooks.
        text (str): Text condition to use. For unconditional or generic behavior, e.g. "a song".
        layer_index (int, optional): The index of the transformer layer whose hidden state
            you wish to extract. If None, the default is the last layer.
    
    Returns:
        torch.Tensor: The hidden state from the specified transformer layer, shape [B, S, embed_dim].
    """
    # Dimensions: B=batch, K=number of codebooks, S=sequence length.
    B, K, S = prompt_tokens.shape
    
    # Compute input embeddings by summing embeddings from each codebook.
    input_emb = sum(model.lm.emb[k](prompt_tokens[:, k]) for k in range(K))
    
    # Build conditioning attributes.
    conditions = [ConditioningAttributes(text={'description': text}) for _ in range(B)]
    
    # Process conditions
    conditions = model.lm.cfg_dropout(conditions)
    conditions = model.lm.att_dropout(conditions)
    tokenized = model.lm.condition_provider.tokenize(conditions)
    condition_tensors = model.lm.condition_provider(tokenized)
    
    # Fuse the audio embeddings with the conditioning.
    fused_input, cross_attention_input = model.lm.fuser(input_emb, condition_tensors)
    # fused_input shape: [B, S, embed_dim]
    
    # Prepare the transformer input by adding positional embeddings.
    transformer = model.lm.transformer  # This is a 'StreamingTransformer'.
    B, T, C = fused_input.shape
    # For a fixed (non-streaming) chunk, we can assume offsets = 0.
    offsets = torch.zeros(B, dtype=torch.long, device=fused_input.device)
    if transformer.positional_embedding in ['sin', 'sin_rope']:
        positions = torch.arange(T, device=fused_input.device).view(1, -1, 1)
        positions = positions + offsets.view(-1, 1, 1)
        pos_emb = create_sin_embedding(positions, C, max_period=transformer.max_period, dtype=fused_input.dtype)
        x = fused_input + transformer.positional_scale * pos_emb
    else:
        x = fused_input

    # Determine which layer to extract.
    num_layers = len(transformer.layers)
    if layer_index is None:
        # use last layer
        layer_index = num_layers - 1
    
    # 7. Iterate through transformer layers until the specified index.
    for idx, layer in enumerate(transformer.layers):
        # We pass cross_attention_src and optionally src_mask.
        # Here we use stage=-1 (i.e. no specific codebook mask) as in LMModel.forward.
        x = transformer._apply_layer(
            layer,
            x,
            cross_attention_src=cross_attention_input,
            src_mask=None
        )
        if idx == layer_index:
            # Return the hidden state at the specified layer.
            return x
    # If layer_index is greater than available layers, return the final hidden state.
    return x

def extract_song_hidden_representation(
    filename: str,
    dir: str,
    model,
    max_chunk_length: float,
    frame_length: float,
    overlap_ratio: float = 0.5,
    layer_index: int = 18
) -> torch.Tensor:
    """
    Process an entire song (wav file) in overlapping chunks and returns a hidden state representation
    for the entire song resampled to have one vector every desired_frame_length seconds.
    
    This function uses the previously defined helper functions:
      - get_intermediate_hidden_state(model, prompt_tokens, text="a song", layer_index=None)
      - resample_hidden_states(hidden_states, model, desired_frame_length, input_duration)
    
    Args:
        wav_file (str): Path to the wav file.
        model: A pretrained MusicGen model.
        max_chunk_length (float): Maximum chunk length in seconds (the LM can only process a limited duration at a time).
        desired_frame_length (float): Desired time interval (in seconds) between hidden state vectors in the final output.
                                      For example, 4096/44100 (~0.093 s) would yield ~10–11 frames per second.
        overlap_ratio (float, optional): Fraction of overlap between consecutive chunks (default 0.5 for 50% overlap).
        
    Returns:
        torch.Tensor: A hidden state tensor for the entire song, of shape [1, T_final, D],
                      where T_final ≈ (total_duration / desired_frame_length) and D is the hidden dimension.
    """
    device = get_torch_device(allow_mps=False)

    model.compression_model = model.compression_model.to(device)

    # Load the audio file.
    wav, sr = torchaudio.load(f"{dir}/audio/{filename}.mp3").to(device)

    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)  # convert to mono

    wav = wav.unsqueeze(0).to(device)  # shape becomes [1, channels, samples]
    if sr != model.sample_rate:
        resampler = Resample(orig_freq=sr, new_freq=model.sample_rate).to(device)
        wav = resampler(wav)

    total_samples = wav.shape[-1]
    total_duration = total_samples / sr  # in seconds

    # Get the frame rate from the compression model.
    fps = model.compression_model.frame_rate  # frames per second, e.g., 50 fps.
    # Global number of frames corresponding to the entire audio (before resampling).
    global_frames = int(round(total_duration * fps))
    
    # Get hidden state dimensionality (assume from first embedding layer).
    D = model.lm.emb[0].embedding_dim

    # Preallocate accumulators for the global hidden state and a weight mask.
    global_hidden = torch.zeros(1, global_frames, D, device=device)
    global_weights = torch.zeros(1, global_frames, 1, device=device)
    
    # Determine chunking parameters.
    chunk_samples = int(max_chunk_length * sr)  # chunk length in samples.
    hop_samples = int(chunk_samples * (1 - overlap_ratio))  # hop size between chunks.
    
    start_sample = 0
    while start_sample < total_samples:
        end_sample = min(start_sample + chunk_samples, total_samples)
        chunk_wav = wav[:, :, start_sample:end_sample]  # shape: [1, channels, chunk_samples]
        
        with torch.no_grad():
            # Encode the chunk to get discrete tokens.
            prompt_tokens, _ = model.compression_model.encode(chunk_wav)
            # prompt_tokens shape: [1, K, S] (K: number of codebooks, S: number of tokens for this chunk)
            
            # Get the intermediate hidden state representation using the helper function.
            hidden_chunk = get_intermediate_hidden_state(model, prompt_tokens, text="a song", layer_index=layer_index)
            # hidden_chunk shape: [1, S, D]
        
        S = hidden_chunk.shape[1]  # number of time steps (frames) for this chunk.
        
        # Determine the start time (in seconds) of the chunk and map it to a frame index.
        chunk_start_time = start_sample / sr
        chunk_start_frame = int(round(chunk_start_time * fps))
        
        # Clip the chunk if it exceeds the global duration.
        if chunk_start_frame + S > global_frames:
            S = global_frames - chunk_start_frame
            hidden_chunk = hidden_chunk[:, :S, :]
        
        # Accumulate the chunk's hidden states and record weights for averaging.
        global_hidden[:, chunk_start_frame:chunk_start_frame + S, :] += hidden_chunk
        global_weights[:, chunk_start_frame:chunk_start_frame + S, :] += 1.0
        
        # Move the window.
        start_sample += hop_samples
    
    # Average overlapping regions.
    # Change device
    global_weights = global_weights.to(global_hidden.device)
    global_hidden = global_hidden / global_weights

    # Resample the global hidden states to have one vector every desired_frame_length seconds.
    resampled_hidden = resample_hidden_states(global_hidden, model, frame_length)
    
    return resampled_hidden