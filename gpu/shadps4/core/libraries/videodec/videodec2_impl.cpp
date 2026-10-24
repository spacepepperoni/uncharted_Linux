// SPDX-FileCopyrightText: Copyright 2024-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <cstdio>
#include "videodec2_impl.h"

#include "common/alignment.h"
#include "common/assert.h"
#include "common/logging/log.h"
#include "video_utils.h"
#include "videodec_error.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <cstdio>

#include "common/support/avdec.h"
#include "core/memory.h"
#include "bbport_movie.h"

#include <algorithm>
#include <cstring>

namespace Libraries::Videodec2 {

VdecDecoder::VdecDecoder(const OrbisVideodec2DecoderConfigInfo& config_info,
                         const OrbisVideodec2DecoderMemoryInfo& memory_info) {
    const AVCodec* codec = avcodec_find_decoder(
        config_info.codec_type == OrbisVideodec2CodecType::Avc ? AV_CODEC_ID_H264
                                                               : AV_CODEC_ID_HEVC);
    ASSERT(codec);

    m_codec_context = avcodec_alloc_context3(codec);
    ASSERT(m_codec_context);
    m_codec_context->width = config_info.max_frame_width;
    m_codec_context->height = config_info.max_frame_height;
    m_max_width = config_info.max_frame_width;
    m_max_height = config_info.max_frame_height;
    std::printf("Videodec2: decoder for %ux%u frames\n", m_max_width, m_max_height);
    m_codec_context->flags |= AV_CODEC_FLAG_COPY_OPAQUE;

    avcodec_open2(m_codec_context, codec, nullptr);
}

VdecDecoder::~VdecDecoder() {
    avcodec_free_context(&m_codec_context);
    sws_freeContext(m_sws_context);
    sws_freeContext(m_scale_context);
    sws_freeContext(m_fit_context);
    av_frame_free(&m_scaled);
}

s32 VdecDecoder::Decode(const OrbisVideodec2InputData& input_data,
                        OrbisVideodec2FrameBuffer& frame_buffer,
                        OrbisVideodec2OutputInfo& output_info) {
    frame_buffer.is_accepted = false;
    output_info.is_valid = false;
    output_info.picture_count = 0;

    if (!input_data.au_data) {
        LOG_ERROR(Lib_Vdec2, "ORBIS_VIDEODEC2_ERROR_ACCESS_UNIT_POINTER");
        return ORBIS_VIDEODEC2_ERROR_ACCESS_UNIT_POINTER;
    }
    if (input_data.au_size == 0) {
        LOG_ERROR(Lib_Vdec2, "ORBIS_VIDEODEC2_ERROR_ACCESS_UNIT_SIZE");
        return ORBIS_VIDEODEC2_ERROR_ACCESS_UNIT_SIZE;
    }

    AVPacket* packet = av_packet_alloc();
    if (!packet) {
        LOG_ERROR(Lib_Vdec2, "Failed to allocate packet");
        return ORBIS_VIDEODEC2_ERROR_API_FAIL;
    }

    packet->data = (u8*)input_data.au_data;
    packet->size = input_data.au_size;
    packet->pts = input_data.pts_data;
    packet->dts = input_data.dts_data;
    packet->opaque = reinterpret_cast<void*>(input_data.attached_data);

    int ret = avcodec_send_packet(m_codec_context, packet);
    if (ret == AVERROR_EOF) {
        // Attempt to flush buffers and try again.
        avcodec_flush_buffers(m_codec_context);
        ret = avcodec_send_packet(m_codec_context, packet);
    }
    if (ret < 0) {
        LOG_ERROR(Lib_Vdec2, "Error sending packet to decoder: {}", ret);
        av_packet_free(&packet);
        return ORBIS_VIDEODEC2_ERROR_API_FAIL;
    }

    AVFrame* frame = av_frame_alloc();
    if (frame == nullptr) {
        LOG_ERROR(Lib_Vdec2, "Failed to allocate frame");
        av_packet_free(&packet);
        return ORBIS_VIDEODEC2_ERROR_API_FAIL;
    }

    ret = avcodec_receive_frame(m_codec_context, frame);
    if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) {
        LOG_TRACE(Lib_Vdec2, "AVERROR_EOF or AVERROR(EAGAIN)");
        av_packet_free(&packet);
        av_frame_free(&frame);
        return ORBIS_OK;
    } else if (ret < 0) {
        LOG_ERROR(Lib_Vdec2, "Error receiving frame from decoder: {}", ret);
        av_packet_free(&packet);
        av_frame_free(&frame);
        return ORBIS_VIDEODEC2_ERROR_API_FAIL;
    }

    if (frame->flags & AV_FRAME_FLAG_INTERLACED) {
        LOG_ERROR(Lib_Vdec2, "Interlaced video output is not suported.");
    }

    if (frame->format != AV_PIX_FMT_NV12) {
        AVFrame* nv12_frame = ConvertNV12Frame(*frame);
        ASSERT(nv12_frame);
        av_frame_free(&frame);
        frame = nv12_frame;
    }
    // Linux fork: in the Steam Deck's 720p mode (scripts/render_720p.py) the game asks for
    // 1280x720 decoders and the collection's movies are 1080p: their frames did not fit its
    // 720p buffers (green and pink logo screens). FitToMaxSize makes them fit.
    // The game's 720p movie textures put the chroma plane after 768 luma rows (rows aligned to
    // 64; 1080p frames come out at 1088 rows either way).
    u32 height_align = 16;
    if (m_max_width && m_max_height &&
        (u32(frame->width) > m_max_width || u32(frame->height) > m_max_height)) {
        if (AVFrame* fitted = FitToMaxSize(*frame)) {
            av_frame_free(&frame);
            frame = fitted;
            height_align = 64;
        }
    }

    Output(*frame, frame_buffer, output_info, height_align);

    av_packet_free(&packet);
    av_frame_free(&frame);
    return ORBIS_OK;
}

s32 VdecDecoder::Flush(OrbisVideodec2FrameBuffer& frame_buffer,
                       OrbisVideodec2OutputInfo& output_info) {
    frame_buffer.is_accepted = false;
    output_info.is_valid = false;
    output_info.picture_count = 0;

    AVFrame* frame = av_frame_alloc();
    if (!frame) {
        LOG_ERROR(Lib_Vdec2, "Failed to allocate frame");
        return ORBIS_VIDEODEC2_ERROR_API_FAIL;
    }

    avcodec_send_packet(m_codec_context, nullptr);
    int ret = avcodec_receive_frame(m_codec_context, frame);
    if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) {
        av_frame_free(&frame);
        return ORBIS_OK;
    } else if (ret < 0) {
        LOG_ERROR(Lib_Vdec2, "Error receiving frame from decoder: {}", ret);
        av_frame_free(&frame);
        return ORBIS_VIDEODEC2_ERROR_API_FAIL;
    }

    if (frame->format != AV_PIX_FMT_NV12) {
        AVFrame* nv12_frame = ConvertNV12Frame(*frame);
        ASSERT(nv12_frame);
        av_frame_free(&frame);
        frame = nv12_frame;
    }
    // Linux fork: in the Steam Deck's 720p mode (scripts/render_720p.py) the game asks for
    // 1280x720 decoders and the collection's movies are 1080p: their frames did not fit its
    // 720p buffers (green and pink logo screens). FitToMaxSize makes them fit.
    // The game's 720p movie textures put the chroma plane after 768 luma rows (rows aligned to
    // 64; 1080p frames come out at 1088 rows either way).
    u32 height_align = 16;
    if (m_max_width && m_max_height &&
        (u32(frame->width) > m_max_width || u32(frame->height) > m_max_height)) {
        if (AVFrame* fitted = FitToMaxSize(*frame)) {
            av_frame_free(&frame);
            frame = fitted;
            height_align = 64;
        }
    }

    Output(*frame, frame_buffer, output_info, height_align);

    av_frame_free(&frame);
    return ORBIS_OK;
}

void VdecDecoder::Output(AVFrame& frame, OrbisVideodec2FrameBuffer& frame_buffer,
                         OrbisVideodec2OutputInfo& output_info, u32 height_align) {
    const bool is_avc = m_codec_context->codec_id == AV_CODEC_ID_H264;
    const u64 info_size =
        is_avc ? sizeof(OrbisVideodec2AvcPictureInfo) : sizeof(OrbisVideodec2HevcPictureInfo);
    Videodec::CopyNV12Data((u8*)frame_buffer.frame_buffer,
                           frame_buffer.frame_buffer_size - info_size, frame, height_align);
    // Render resolution (bbport_movie.h): the decoded layout (chroma after the luma rows aligned
    // to 16), and with a copy scaled to the movie display size the frame is reported at that size:
    // the movie player's conversion shader spans the frame size it is given.
    const u64 base = (u64)frame_buffer.frame_buffer;
    BbMovie::RecordFrame(base, (u32)frame.width, (u32)frame.height, Common::AlignUp<u32>(frame.width, 64),
                         Common::AlignUp<u32>(frame.height, height_align));
    u32 shown_width = (u32)frame.width, shown_height = (u32)frame.height;
    u32 shown_align = height_align; // the Deck's 720p fit (FitToMaxSize) aligns rows to 64
    if (WriteMovieCopy(frame, base)) {
        BbMovie::DisplaySize(shown_width, shown_height);
        shown_align = 16;
    }
    frame_buffer.is_accepted = true;

    const auto width = Common::AlignUp<u32>(shown_width, 16);
    const auto pitch = Common::AlignUp<u32>(shown_width, 64);
    const auto height = Common::AlignUp<u32>(shown_height, shown_align);
    // The picture info follows the decoded frame (its own size, not the display size).
    const auto decoded_pitch = Common::AlignUp<u32>(frame.width, 64);
    const auto decoded_height = Common::AlignUp<u32>(frame.height, height_align);

    output_info.is_valid = true;
    output_info.is_error_frame = false;
    output_info.picture_count = 1; // TODO: 2 pictures for interlaced video
    output_info.codec_type = is_avc ? OrbisVideodec2CodecType::Avc : OrbisVideodec2CodecType::Hevc;
    output_info.frame_width = width;
    output_info.frame_pitch = pitch;
    output_info.frame_height = height;
    output_info.frame_buffer = frame_buffer.frame_buffer;
    output_info.frame_buffer_size = (decoded_pitch * decoded_height * 3) / 2;

    // Only set frameFormat and framePitchInBytes if the game uses the newer struct version.
    if (output_info.this_size == sizeof(OrbisVideodec2OutputInfo)) {
        output_info.frame_format = 0;
        output_info.frame_pitch_in_bytes = pitch;
    }

    if (is_avc) {
        auto& picture_info = *(OrbisVideodec2AvcPictureInfo*)((u8*)output_info.frame_buffer +
                                                              output_info.frame_buffer_size);

        picture_info = {};
        picture_info.is_valid = true;

        picture_info.pts_data = frame.pts;
        picture_info.dts_data = frame.pkt_dts;
        picture_info.attached_data = reinterpret_cast<u64>(frame.opaque);

        picture_info.frame_crop_top_offset = 0;
        picture_info.frame_crop_left_offset = 0;
        picture_info.frame_crop_right_offset = pitch - shown_width;
        picture_info.frame_crop_bottom_offset = height - shown_height;
    } else {
        auto& picture_info = *(OrbisVideodec2HevcPictureInfo*)((u8*)output_info.frame_buffer +
                                                               output_info.frame_buffer_size);
        picture_info = {};
        picture_info.is_valid = true;

        picture_info.pts_data = frame.pts;
        picture_info.dts_data = frame.pkt_dts;
        picture_info.attached_data = reinterpret_cast<u64>(frame.opaque);

        picture_info.frame_crop_top_offset = 0;
        picture_info.frame_crop_left_offset = 0;
        picture_info.frame_crop_right_offset = pitch - shown_width;
        picture_info.frame_crop_bottom_offset = height - shown_height;
    }
}

// Render resolution (BB_MOVIE_SIZE, bbport_movie.h; after BilalReloaded's Uncharted PC port): the
// frame also scaled to the display size the movie player reads it with, into the scratch frame
// of the game's frame buffer at base. True when written.
bool VdecDecoder::WriteMovieCopy(const AVFrame& frame, u64 base) {
    u32 width = 0, height = 0;
    if (!BbMovie::DisplaySize(width, height) ||
        ((u32)frame.width == width && (u32)frame.height == height)) {
        return false;
    }
    u8* dst = BbMovie::ScratchFrame(base);
    if (!dst) {
        return false;
    }
    if (!m_scaled) {
        m_scaled = av_frame_alloc();
    }
    if (!m_scaled) {
        return false;
    }
    // The movie keeps its own shape inside the display size: black bars at the top and bottom
    // (16:10) or at the sides (ultrawide) instead of a stretched picture. 16:9 sizes fill it.
    u32 fit_width = width, fit_height = height;
    if ((u64)frame.width * height > (u64)frame.height * width) {
        fit_height = std::min(height, (u32)((u64)width * frame.height / frame.width) & ~1u);
    } else {
        fit_width = std::min(width, (u32)((u64)height * frame.width / frame.height) & ~1u);
    }
    const u32 left = (width - fit_width) / 2 & ~1u, top = (height - fit_height) / 2 & ~1u;
    if ((u32)m_scaled->width != fit_width || (u32)m_scaled->height != fit_height) {
        av_frame_unref(m_scaled);
        m_scaled->format = AV_PIX_FMT_NV12;
        m_scaled->width = (int)fit_width;
        m_scaled->height = (int)fit_height;
        if (av_frame_get_buffer(m_scaled, 0) < 0) {
            av_frame_unref(m_scaled);
            return false;
        }
    }
    m_scale_context = sws_getCachedContext(m_scale_context, frame.width, frame.height,
                                           AV_PIX_FMT_NV12, (int)fit_width, (int)fit_height,
                                           AV_PIX_FMT_NV12, SWS_BICUBIC, nullptr, nullptr, nullptr);
    if (!m_scale_context || sws_scale(m_scale_context, frame.data, frame.linesize, 0, frame.height,
                                      m_scaled->data, m_scaled->linesize) < 0) {
        return false;
    }
    const u32 pitch = BbMovie::ScaledPitch(), rows = BbMovie::ScaledRows();
    const u32 chroma_pitch = BbMovie::ScaledChromaPitch();
    const u64 bytes = BbMovie::ScaledFrameBytes();
    // Black (video range) around the picture.
    m_movie_copy.assign(bytes, 128);
    u8* copy = m_movie_copy.data();
    u8* chroma = copy + (u64)pitch * rows;
    std::memset(copy, 16, (u64)pitch * rows);
    for (u32 y = 0; y < fit_height; ++y) {
        std::memcpy(copy + (u64)(top + y) * pitch + left,
                    m_scaled->data[0] + (u64)y * m_scaled->linesize[0], fit_width);
        if (y < fit_height / 2) {
            std::memcpy(chroma + (u64)(top / 2 + y) * chroma_pitch + left,
                        m_scaled->data[1] + (u64)y * m_scaled->linesize[1], fit_width);
        }
    }
    // The rows up to the aligned height repeat the last one (sampling at the bottom edge reads
    // them at heights that aren't a multiple of 16, e.g. 1620).
    for (u32 y = height; y < rows; ++y) {
        std::memcpy(copy + (u64)y * pitch, copy + (u64)(height - 1) * pitch, width);
    }
    for (u32 y = height / 2; y < rows / 2; ++y) {
        std::memcpy(chroma + (u64)y * chroma_pitch, chroma + (u64)(height / 2 - 1) * chroma_pitch,
                    width);
    }
    // The GPU caches learn of the new frame explicitly (one write through the backing view, no
    // page faults per row). Invalidated before (any GPU copy of these pages goes back first)
    // and after the write.
    auto* memory = Core::Memory::Instance();
    const VAddr address = reinterpret_cast<VAddr>(dst);
    memory->InvalidateMemory(address, bytes);
    if (!memory->TryWriteBacking(dst, copy, bytes)) {
        std::memcpy(dst, copy, bytes);
    }
    memory->InvalidateMemory(address, bytes);
    return true;
}

s32 VdecDecoder::Reset() {
    avcodec_flush_buffers(m_codec_context);
    return ORBIS_OK;
}

AVFrame* VdecDecoder::FitToMaxSize(AVFrame& frame) {
    // The frame handed over has the decoder's maximum size. The collection's movie shader in its
    // 720p mode samples the picture at 720p/1080p of each screen position from the top left
    // (its 1080p movies were made for 1080p): the picture is scaled to that share of the frame,
    // top left, the rest black, and comes out full screen.
    const u32 width = m_max_width & ~1u;
    const u32 height = m_max_height & ~1u;
    // Rounded up to even sizes: the shader reaches 1280 * 2/3 = 853.3 (852 left a bright line
    // at the right edge of the screen).
    const auto share = [](u32 size, int full) {
        const u64 span = u64(size) * size;
        return std::min<u32>(size, u32((span + u32(full) - 1) / u32(full) + 1) & ~1u);
    };
    const u32 pic_width = share(width, std::max(frame.width, 1));
    const u32 pic_height = share(height, std::max(frame.height, 1));
    static bool logged = false;
    if (!logged) {
        logged = true;
        std::printf("Videodec2: %dx%d frames as %ux%u pictures in %ux%u frames\n", frame.width,
                    frame.height, pic_width, pic_height, width, height);
    }
    AVFrame* fitted = av_frame_alloc();
    fitted->pts = frame.pts;
    fitted->pkt_dts = frame.pkt_dts;
    fitted->format = AV_PIX_FMT_NV12;
    fitted->width = int(width);
    fitted->height = int(height);
    fitted->sample_aspect_ratio = frame.sample_aspect_ratio;
    fitted->opaque = frame.opaque;
    av_frame_get_buffer(fitted, 0);
    for (u32 y = 0; y < height; ++y) {
        std::memset(fitted->data[0] + y * fitted->linesize[0], 16, width); // black
    }
    for (u32 y = 0; y < height / 2; ++y) {
        std::memset(fitted->data[1] + y * fitted->linesize[1], 128, width);
    }
    m_fit_context = sws_getCachedContext(m_fit_context, frame.width, frame.height, AV_PIX_FMT_NV12,
                                         int(pic_width), int(pic_height), AV_PIX_FMT_NV12,
                                         SWS_BILINEAR, nullptr, nullptr, nullptr);
    if (!m_fit_context || sws_scale(m_fit_context, frame.data, frame.linesize, 0, frame.height,
                                    fitted->data, fitted->linesize) < 0) {
        av_frame_free(&fitted);
        return nullptr;
    }
    return fitted;
}

AVFrame* VdecDecoder::ConvertNV12Frame(AVFrame& frame) {
    AVFrame* nv12_frame = av_frame_alloc();
    nv12_frame->pts = frame.pts;
    nv12_frame->pkt_dts = frame.pkt_dts < 0 ? 0 : frame.pkt_dts;
    nv12_frame->format = AV_PIX_FMT_NV12;
    nv12_frame->width = frame.width;
    nv12_frame->height = frame.height;
    nv12_frame->sample_aspect_ratio = frame.sample_aspect_ratio;
    nv12_frame->crop_top = frame.crop_top;
    nv12_frame->crop_bottom = frame.crop_bottom;
    nv12_frame->crop_left = frame.crop_left;
    nv12_frame->crop_right = frame.crop_right;
    nv12_frame->opaque = frame.opaque;

    av_frame_get_buffer(nv12_frame, 0);

    if (m_sws_context == nullptr) {
        m_sws_context = sws_getContext(frame.width, frame.height, AVPixelFormat(frame.format),
                                       nv12_frame->width, nv12_frame->height, AV_PIX_FMT_NV12,
                                       SWS_FAST_BILINEAR, nullptr, nullptr, nullptr);
    }

    const auto res = sws_scale(m_sws_context, frame.data, frame.linesize, 0, frame.height,
                               nv12_frame->data, nv12_frame->linesize);
    if (res < 0) {
        LOG_ERROR(Lib_Vdec2, "Could not convert to NV12: {}", av_err2str(res));
        return nullptr;
    }

    return nv12_frame;
}

void GameResolution(s32& width, s32& height) {
    static s32 w = -1, h = 0;
    if (w < 0) {
        w = 0;
        unsigned pw = 0, ph = 0;
        if (const char* res = std::getenv("BB_GAME_RES");
            res && std::sscanf(res, "%ux%u", &pw, &ph) == 2 && pw >= 640 && ph >= 360 &&
            !(pw == 1920 && ph == 1080)) {
            w = static_cast<s32>(pw & ~1u);
            h = static_cast<s32>(ph & ~1u);
        }
    }
    width = w;
    height = h;
}

} // namespace Libraries::Videodec2
