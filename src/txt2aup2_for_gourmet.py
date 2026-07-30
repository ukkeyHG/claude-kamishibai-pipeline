#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
テキストファイルから AivisSpeech プロジェクト (.aisp) と、
AviUtl2用のプロジェクトファイル (.aup2) を一挙に同時自動生成するスクリプト。
（孤独のグルメ風・紙芝居自動生成プロジェクト専用カスタマイズ版）

使い方:
    python src/txt2aup2_for_gourmet.py episodes/ep01_fukuoka/narration.json
"""

import sys
import json
import uuid
import argparse
import urllib.request
import urllib.parse
import wave
from pathlib import Path

# === AivisSpeech デフォルト設定 ===
DEFAULT_APP_VERSION = "1.1.0"
DEFAULT_ENGINE_ID = "1b4a5014-d9fd-11ee-b97d-83c170a68ed3"
DEFAULT_SPEAKER_ID = "e545041a-dee6-4dd3-a78d-eb47e7023d6c"
DEFAULT_STYLE_ID = 13055520
DEFAULT_PRESET_KEY = "bb3b19b6-336a-4523-a851-a31567853de8"
DEFAULT_ENGINE_URL = "http://127.0.0.1:10101"
DEFAULT_SPEED_SCALE = 1.2

# === AviUtl2 デフォルト設定 ===
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 60

# 字幕設定
DEFAULT_FONT_NAME = "_けいふぉんと"
DEFAULT_FONT_SIZE = 90
DEFAULT_COLOR = "3232e3"          
DEFAULT_COLOR2 = "000000"         
DEFAULT_ALIGN = 7                 # 7 = 中央揃え[下]
DEFAULT_POS_X = 0.0
DEFAULT_POS_Y = 480.0             # 1920x1080の下寄り
DEFAULT_POS_Z = 0.0
DEFAULT_SCALE_RATE = 100.00
DEFAULT_FADE_IN = 0.10
DEFAULT_FADE_OUT = 0.10

# アニメーション効果
DEFAULT_ANIM_NAME = "縁取り"
DEFAULT_ANIM_PARAM = "サイズ=5;ぼかし=5;縁色=ffffff"

DEFAULT_CHARS_PER_SEC = 7.5
DEFAULT_GAP_SECONDS = 2
DEFAULT_MIN_FRAMES = 60


def read_input_lines(file_path: Path) -> list:
    if file_path.suffix.lower() == ".json":
        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
            
            lines = []
            for i, scene in enumerate(data.get("scenes", [])):
                scene_num = scene.get("scene_num", i + 1)
                marker = f"# @IMAGE: images/scene_{scene_num:02d}.png"
                if i > 0:
                    lines.append("# @SCENE_GAP")
                lines.append(marker)
                
                text = scene.get("text", "")
                raw_lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
                
                for line in raw_lines:
                    trimmed = line.strip()
                    if trimmed == "":
                        lines.append("")
                    else:
                        normalized = trimmed.replace("\u301c", "\uff5e")
                        lines.append(normalized)
            
            while lines and lines[-1] == "":
                lines.pop()
                
            return lines
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            return []
    else:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="cp932")
        
        raw_lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        
        while raw_lines and raw_lines[-1].strip() == "":
            raw_lines.pop()
            
        lines = []
        for line in raw_lines:
            trimmed = line.strip()
            if trimmed.startswith("#"):
                if trimmed.startswith("# @IMAGE:") or trimmed.startswith("# @VIDEO:"):
                    if lines:
                        lines.append("# @SCENE_GAP")
                    lines.append(trimmed)
                continue
                
            if trimmed == "":
                lines.append("")
            else:
                normalized = trimmed.replace("\u301c", "\uff5e")
                lines.append(normalized)
        return lines


def sanitize_filename(name: str) -> str:
    invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '\n', '\r', '\t', ',', '，']
    safe_name = name
    for c in invalid_chars:
        safe_name = safe_name.replace(c, '')
    return safe_name.strip()


def get_audio_query(text: str, style_id: int, engine_url: str) -> dict:
    url = f"{engine_url}/audio_query"
    params = {"text": text, "speaker": style_id}
    query_string = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query_string}", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3.0) as res:
            if res.status == 200:
                return json.loads(res.read().decode("utf-8"))
    except Exception:
        pass
    return None

def create_fallback_query(text: str) -> dict:
    return {
        "accentPhrases": [], "speedScale": 1.0, "intonationScale": 1.0,
        "tempoDynamicsScale": 1.0, "pitchScale": 0.0, "volumeScale": 1.0,
        "pauseLengthScale": 1.0, "prePhonemeLength": 0.1, "postPhonemeLength": 0.1,
        "outputSamplingRate": "engineDefault", "outputStereo": False, "kana": text
    }

def convert_query_to_aisp_format(query: dict) -> dict:
    # 省略形ですが、今回の主な目的は .aup2 の出力なので、簡易版を実装。
    return query

def get_wav_bytes(query_data: dict, style_id: int, engine_url: str) -> bytes:
    url = f"{engine_url}/synthesis"
    params = {"speaker": style_id}
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"
    
    data_bytes = json.dumps(query_data).encode("utf-8")
    req = urllib.request.Request(full_url, data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60.0) as response:
            if response.status == 200:
                return response.read()
    except Exception as e:
        print(f"警告: 音声合成失敗: {e}")
    return None

def get_wav_duration_frames(wav_path: Path, fps: int) -> int:
    try:
        with wave.open(str(wav_path), 'rb') as w:
            frames = w.getnframes()
            rate = w.getframerate()
            duration_sec = frames / float(rate)
            return max(1, round(duration_sec * fps))
    except Exception:
        return int(fps)

def get_video_duration_frames(video_path: Path, fps: int) -> int:
    try:
        import subprocess
        ps_script = f"$shell = New-Object -ComObject Shell.Application; $folder = $shell.NameSpace('{video_path.parent.resolve()}'); $file = $folder.ParseName('{video_path.name}'); $dur = $file.ExtendedProperty('System.Media.Duration'); if ($dur) {{ [math]::Round($dur / 10000000 * {fps}) }} else {{ 0 }}"
        result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return max(1, int(result.stdout.strip()))
    except Exception:
        pass
    return 0

def encode_text_field(s: str) -> str:
    # aup2 では hex エンコード不要で直接テキストを書き込むためそのまま返す
    return s


# ==========================================
# AviUtl2 (.aup2) オブジェクト組み立て処理
# ==========================================
def build_aup2_header(out_path: Path, args) -> list:
    L = []
    L.append("[project]")
    L.append("version=2010100")
    L.append(f"file={str(out_path.absolute())}")
    L.append("display.scene=0")
    L.append("preview.scene=0")
    L.append("[scene.0]")
    L.append("scene=0")
    L.append("name=Root")
    L.append(f"video.width={args.width}")
    L.append(f"video.height={args.height}")
    L.append(f"video.rate={args.fps}")
    L.append("video.scale=1")
    L.append("audio.rate=44100")
    L.append("cursor.frame=0")
    L.append("cursor.layer=1")
    return L

def build_aup2_image(index: int, start_frame: int, end_frame: int, img_rel_path: str, base_dir: Path, args) -> list:
    L = []
    L.append(f"[{index}]")
    L.append(f"layer=0")  # 背景レイヤー
    L.append(f"frame={start_frame},{end_frame}")
    L.append("camera=0")
    
    img_path = base_dir / img_rel_path
    win_path = str(img_path.absolute()).replace('/', '\\')
    
    L.append(f"[{index}.0]")
    L.append("effect.name=画像ファイル")
    L.append(f"ファイル={win_path}")
    L.append("表示番号=0,0,再生範囲,0")
    L.append("再生速度=100.00")
    L.append("ループ再生=0")
    L.append("連番ファイル=0")
    
    L.append(f"[{index}.1]")
    L.append("effect.name=標準描画")
    L.append("X=0.00")
    L.append("Y=0.00")
    L.append("Z=0.00")
    L.append("Group=1")
    L.append("中心X=0.00")
    L.append("中心Y=0.00")
    L.append("中心Z=0.00")
    L.append("Group3=1")
    L.append("X軸回転=0.00")
    L.append("Y軸回転=0.00")
    L.append("Z軸回転=0.00")
    L.append("Group2=1")
    L.append("拡大率=100.000")
    L.append("縦横比=0.000")
    L.append("透明度=0.00")
    L.append("合成モード=通常")
    
    L.append(f"[{index}.2]")
    L.append("effect.name=フェード")
    L.append(f"イン={args.fade_in:.2f}")
    L.append(f"アウト={args.fade_out:.2f}")
    return L

def build_aup2_video(index_v: int, index_a: int, start_frame: int, end_frame: int, vid_rel_path: str, base_dir: Path, args) -> list:
    L = []
    vid_path = base_dir / vid_rel_path
    win_path = str(vid_path.absolute()).replace('/', '\\')
    
    # 映像レイヤー
    L.append(f"[{index_v}]")
    L.append(f"layer=0")
    L.append(f"frame={start_frame},{end_frame}")
    L.append("camera=0")
    L.append(f"group={index_v}")
    
    L.append(f"[{index_v}.0]")
    L.append("effect.name=動画ファイル")
    L.append("再生位置=1.000")
    L.append("再生速度=100.00")
    L.append(f"ファイル={win_path}")
    L.append("トラック=0")
    L.append("ループ再生=0")
    L.append("音声付き=0")
    
    L.append(f"[{index_v}.1]")
    L.append("effect.name=標準描画")
    L.append("X=0.00")
    L.append("Y=0.00")
    L.append("Z=0.00")
    L.append("Group=1")
    L.append("中心X=0.00")
    L.append("中心Y=0.00")
    L.append("中心Z=0.00")
    L.append("Group3=1")
    L.append("X軸回転=0.00")
    L.append("Y軸回転=0.00")
    L.append("Z軸回転=0.00")
    L.append("Group2=1")
    L.append("拡大率=100.000")
    L.append("縦横比=0.000")
    L.append("透明度=0.00")
    L.append("合成モード=通常")
    
    L.append(f"[{index_v}.2]")
    L.append("effect.name=フェード")
    L.append(f"イン={args.fade_in:.2f}")
    L.append(f"アウト={args.fade_out:.2f}")
    
    # 音声レイヤー (Layer 1)
    L.append(f"[{index_a}]")
    L.append(f"layer=1")
    L.append(f"frame={start_frame},{end_frame}")
    L.append(f"group={index_v}")
    
    L.append(f"[{index_a}.0]")
    L.append("effect.name=音声ファイル")
    L.append("再生位置=0.000")
    L.append("再生速度=100.00")
    L.append(f"ファイル={win_path}")
    L.append("トラック=0")
    L.append("ループ再生=0")
    
    L.append(f"[{index_a}.1]")
    L.append("effect.name=音声再生")
    L.append("音量=100.00")
    L.append("左右=0.00")
    return L

def build_aup2_text(index: int, start_frame: int, end_frame: int, text: str, args) -> list:
    L = []
    L.append(f"[{index}]")
    L.append(f"layer=2")  # 字幕レイヤー
    L.append(f"frame={start_frame},{end_frame}")
    
    L.append(f"[{index}.0]")
    L.append("effect.name=テキスト")
    L.append(f"サイズ={args.font_size:.2f}")
    L.append("字間=0.00")
    L.append("行間=0.00")
    L.append("表示速度=0.00")
    L.append(f"フォント={args.font_name}")
    L.append(f"文字色={args.font_color}")
    L.append(f"影・縁色={args.font_color2}")
    L.append("文字装飾=標準文字")
    L.append("文字揃え=中央揃え[中]")
    L.append("B=0")
    L.append("I=0")
    L.append(f"テキスト={text}")
    L.append("文字毎に個別オブジェクト=0")
    L.append("自動スクロール=0")
    L.append("移動座標上に表示=0")
    L.append("オブジェクトの長さを自動調節=0")
    
    L.append(f"[{index}.1]")
    L.append("effect.name=標準描画")
    L.append(f"X={args.pos_x:.2f}")
    L.append(f"Y={args.pos_y:.2f}")
    L.append(f"Z={args.pos_z:.2f}")
    L.append("Group=1")
    L.append("中心X=0.00")
    L.append("中心Y=0.00")
    L.append("中心Z=0.00")
    L.append("Group3=1")
    L.append("X軸回転=0.00")
    L.append("Y軸回転=0.00")
    L.append("Z軸回転=0.00")
    L.append("Group2=1")
    L.append(f"拡大率={args.scale_rate:.3f}")
    L.append("縦横比=0.000")
    L.append("透明度=0.00")
    L.append("合成モード=通常")
    
    L.append(f"[{index}.2]")
    L.append(f"effect.name={args.anim_name}")
    for param in args.anim_param.split(';'):
        L.append(param)
        
    L.append(f"[{index}.3]")
    L.append("effect.name=フェード")
    L.append(f"イン={args.fade_in:.2f}")
    L.append(f"アウト={args.fade_out:.2f}")
    return L

def build_aup2_audio(index: int, start_frame: int, end_frame: int, wav_path: Path, base_dir: Path) -> list:
    L = []
    L.append(f"[{index}]")
    L.append(f"layer=3")  # 音声レイヤー
    L.append(f"frame={start_frame},{end_frame}")
    
    win_path = str(wav_path.absolute()).replace('/', '\\')
    
    L.append(f"[{index}.0]")
    L.append("effect.name=音声ファイル")
    L.append("再生位置=0.000,0.000,再生範囲,0")
    L.append("再生速度=100.00")
    L.append(f"ファイル={win_path}")
    L.append("トラック=0")
    L.append("ループ再生=0")
    
    L.append(f"[{index}.1]")
    L.append("effect.name=音声再生")
    L.append("音量=100.00")
    L.append("左右=0.00")
    return L


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", type=str)
    parser.add_argument("output_file", type=str, nargs="?")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--style-id", type=int, default=DEFAULT_STYLE_ID)
    parser.add_argument("--engine-url", type=str, default=DEFAULT_ENGINE_URL)
    
    # テキストパラメータ
    parser.add_argument("--font-name", type=str, default=DEFAULT_FONT_NAME)
    parser.add_argument("--font-size", type=int, default=DEFAULT_FONT_SIZE)
    parser.add_argument("--font-color", type=str, default=DEFAULT_COLOR)
    parser.add_argument("--font-color2", type=str, default=DEFAULT_COLOR2)
    parser.add_argument("--pos-x", type=float, default=DEFAULT_POS_X)
    parser.add_argument("--pos-y", type=float, default=DEFAULT_POS_Y)
    parser.add_argument("--pos-z", type=float, default=DEFAULT_POS_Z)
    parser.add_argument("--scale-rate", type=float, default=DEFAULT_SCALE_RATE)
    parser.add_argument("--fade-in", type=float, default=DEFAULT_FADE_IN)
    parser.add_argument("--fade-out", type=float, default=DEFAULT_FADE_OUT)
    parser.add_argument("--anim-name", type=str, default=DEFAULT_ANIM_NAME)
    parser.add_argument("--anim-param", type=str, default=DEFAULT_ANIM_PARAM)
    
    args = parser.parse_args()
    
    in_path = Path(args.input_file)
    if in_path.is_dir():
        in_path = in_path / "narration.json"
        
    if not in_path.exists():
        print(f"Error: Input file not found: {in_path}")
        return
    out_path = Path(args.output_file).absolute() if args.output_file else in_path.with_suffix(".aisp").absolute()
    aup2_out_path = out_path.with_suffix(".aup2").absolute()
    
    lines = read_input_lines(in_path)
    if not lines: return

    wav_dir = out_path.parent / "audio"
    wav_dir.mkdir(parents=True, exist_ok=True)
    
    dialogues = []
    current_media = None
    wav_idx = 1
    
    print("音声合成とAUP2プロジェクトを生成中...")
    for line in lines:
        if line.startswith("# @IMAGE:"):
            current_media = ("image", line.replace("# @IMAGE:", "").strip())
            continue
        elif line.startswith("# @VIDEO:"):
            current_media = ("video", line.replace("# @VIDEO:", "").strip())
            continue
            
        if line == "# @SCENE_GAP":
            dialogues.append({"text": "", "wav_path": None, "media": current_media, "gap_type": "scene"})
            continue
            
        if line == "":
            dialogues.append({"text": "", "wav_path": None, "media": current_media, "gap_type": "breath"})
            continue
            
        query = get_audio_query(line, args.style_id, args.engine_url)
        if not query:
            query = create_fallback_query(line)
        
        import hashlib
        safe = sanitize_filename(line)[:10]
        hash_s = hashlib.md5(line.encode()).hexdigest()[:6]
        w_path = wav_dir / f"{wav_idx:03d}_{hash_s}_{safe}.wav"
        
        if not w_path.exists():
            data = get_wav_bytes(query, args.style_id, args.engine_url)
            if data: w_path.write_bytes(data)
            
        dialogues.append({"text": line, "wav_path": w_path, "media": current_media})
        wav_idx += 1

    # === .aup2 の出力処理 ===
    print("AviUtl2用 .aup2 プロジェクトを構築中...")
    gap_frames = DEFAULT_GAP_SECONDS * args.fps
    breath_frames = max(1, int(0.8 * args.fps))
    temp_cursor = 1
    
    # 1. 各ダイアログのフレームタイミングを事前計算
    current_media_start_f = 1
    current_vid_dur = 0
    last_media_path = None
    
    for item in dialogues:
        text = item["text"]
        wav_path = item["wav_path"]
        media = item.get("media")
        
        # メディアの開始位置と本来の長さを追跡
        if media:
            m_type, m_path = media
            if m_path != last_media_path:
                current_media_start_f = temp_cursor
                last_media_path = m_path
                if m_type == "video":
                    current_vid_dur = get_video_duration_frames(out_path.parent / m_path, args.fps)
                else:
                    current_vid_dur = 0
        
        if text == "":
            if item.get("gap_type") == "scene":
                dur_frames = gap_frames
                # 空行かつ背景が動画の場合、残り時間を計算してストレッチ
                if media and media[0] == "video":
                    elapsed = temp_cursor - current_media_start_f
                    remaining = current_vid_dur - elapsed
                    if remaining > gap_frames:
                        dur_frames = remaining
            else:
                dur_frames = breath_frames
                    
            item["start_f"] = temp_cursor
            item["end_f"] = temp_cursor + dur_frames - 1
            item["is_gap"] = True
            temp_cursor += dur_frames
            continue
            
        dur_frames = DEFAULT_MIN_FRAMES
        if wav_path and wav_path.exists():
            dur_frames = get_wav_duration_frames(wav_path, args.fps)
            
        item["start_f"] = temp_cursor
        item["end_f"] = temp_cursor + dur_frames - 1
        item["is_gap"] = False
        temp_cursor += dur_frames

    # 2. メディア（動画・画像）の連続スパンを計算
    media_spans = []
    current_span = None
    
    for item in dialogues:
        m = item.get("media")
        # メディアが切り替わった場合（同じメディアでも、違うファイルなら切り替え）
        if current_span and m != current_span["media"]:
            current_span["end_f"] = item["start_f"] - 1
            media_spans.append(current_span)
            current_span = None
            
        if m and not current_span:
            current_span = {"media": m, "start_f": item["start_f"]}
            
    # 最後のスパンの終了フレームを設定
    if current_span:
        current_span["end_f"] = temp_cursor - 1
        media_spans.append(current_span)

    # 3. オブジェクトの書き出し
    obj_index = 0
    aup2_lines = build_aup2_header(aup2_out_path, args)
    
    # レイヤー0-1: 背景メディア（長尺オブジェクトとして配置）
    for span in media_spans:
        m_type, m_path = span["media"]
        if m_type == "image":
            aup2_lines.extend(build_aup2_image(obj_index, span["start_f"], span["end_f"], m_path, out_path.parent, args))
            obj_index += 1
        elif m_type == "video":
            # 動画は映像と音声の2レイヤーを使用
            aup2_lines.extend(build_aup2_video(obj_index, obj_index+1, span["start_f"], span["end_f"], m_path, out_path.parent, args))
            obj_index += 2

    # レイヤー2: テキスト（字幕）
    for i, item in enumerate(dialogues):
        if item.get("is_gap"):
            continue
            
        start_f = item["start_f"]
        end_f = item["end_f"]
        
        # 息継ぎ（breath）ギャップ中は直前の字幕をそのまま表示し続ける
        curr_idx = i + 1
        while curr_idx < len(dialogues) and dialogues[curr_idx].get("is_gap") and dialogues[curr_idx].get("gap_type") == "breath":
            end_f = dialogues[curr_idx]["end_f"]
            curr_idx += 1
            
        aup2_lines.extend(build_aup2_text(obj_index, start_f, end_f, item["text"], args))
        obj_index += 1

    # レイヤー3: 音声ファイル
    for item in dialogues:
        if item.get("is_gap") or not item.get("wav_path"):
            continue
        aup2_lines.extend(build_aup2_audio(obj_index, item["start_f"], item["end_f"], item["wav_path"], out_path.parent))
        obj_index += 1
        
    try:
        aup2_out_path.write_text("\n".join(aup2_lines), encoding="utf-8")
        print(f"成功: AviUtl2プロジェクトを出力しました -> {aup2_out_path}")
    except Exception as e:
        print(f"エラー: .aup2 の書き込みに失敗しました: {e}")

if __name__ == "__main__":
    main()
