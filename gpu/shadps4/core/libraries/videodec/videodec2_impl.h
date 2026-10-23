// SPDX-FileCopyrightText: Copyright 2024-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <vector>

#include "videodec2.h"

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>
}

namespace Libraries::Videodec2 {

/// BB_GAME_RES (WxH): the games read decoded movie frames at their display size, so frames are
/// fitted (aspect kept, black bars) into a canvas of that size. 0 when the game runs at 1920x1080.
void GameResolution(s32& width, s32& height);

class VdecDecoder {
public:
    VdecDecoder(const OrbisVideodec2DecoderConfigInfo& configInfo,
                const OrbisVideodec2DecoderMemoryInfo& memoryInfo);
    ~VdecDecoder();

    s32 Decode(const OrbisVideodec2InputData& inputData, OrbisVideodec2FrameBuffer& frameBuffer,
               OrbisVideodec2OutputInfo& outputInfo);
    s32 Flush(OrbisVideodec2FrameBuffer& frameBuffer, OrbisVideodec2OutputInfo& outputInfo);
    s32 Reset();

private:
    AVFrame* ConvertNV12Frame(AVFrame& frame);
    /// Linux fork: a frame larger than the decoder's configured maximum, scaled down to fit it.
    AVFrame* FitToMaxSize(AVFrame& frame);
    /// Render resolution (BB_MOVIE_SIZE, bbport_movie.h): the frame also scaled to the display
    /// size the movie player reads it with, into the scratch frame of the game's frame buffer at
    /// base. True when written.
    bool WriteMovieCopy(const AVFrame& frame, u64 base);
    /// Copies a decoded frame into the game's buffer and fills the output info (Decode, Flush).
    void Output(AVFrame& frame, OrbisVideodec2FrameBuffer& frame_buffer,
                OrbisVideodec2OutputInfo& output_info, u32 height_align = 16);

private:
    AVCodecContext* m_codec_context = nullptr;
    SwsContext* m_sws_context = nullptr;
    SwsContext* m_scale_context = nullptr;
    AVFrame* m_scaled = nullptr;
    std::vector<u8> m_movie_copy;
    SwsContext* m_fit_context = nullptr;
    u32 m_max_width = 0;
    u32 m_max_height = 0;
};

} // namespace Libraries::Videodec2