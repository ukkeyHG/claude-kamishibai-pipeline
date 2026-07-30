from typing import List
from pydantic import BaseModel, Field

class Scene(BaseModel):
    scene_num: int = Field(description="シーン番号（1〜13）")
    visual_ja: str = Field(description="情景の日本語説明（画像生成の元となるビジュアルイメージ）")
    monologue: str = Field(description="薫の独白（モノローグ）。必ず日本語。1シーンにつき3〜5行程度の文章。")

class DesignOutput(BaseModel):
    episode_title: str = Field(description="エピソードのタイトル（例：香川・うどん出張編）")
    dishes: List[str] = Field(description="選定された3〜4つの郷土料理名", max_items=4)
    scenes: List[Scene] = Field(description="13シーンのプロット", min_items=13, max_items=13)

class NarrationScene(BaseModel):
    scene_num: int
    image_marker: str = Field(description="例: # @IMAGE: assets/scene_01.png")
    text: str = Field(description="TTSで音声化されるテキスト。空行はポーズとして扱うため適宜改行を入れる。")

class NarrationOutput(BaseModel):
    scenes: List[NarrationScene]

class ImagePromptScene(BaseModel):
    scene_num: int
    positive_prompt: str = Field(description="Stable Diffusion XL用の英語ポジティブプロンプト。カンマ区切り。")
    negative_prompt: str = Field(description="Stable Diffusion XL用の英語ネガティブプロンプト。または '-'")

class ImagePromptOutput(BaseModel):
    scenes: List[ImagePromptScene]

class ReviewOutput(BaseModel):
    status: str = Field(description='"approve" または "revise"')
    feedback: list[str] = Field(description="修正が必要な場合、具体的な指摘事項のリスト。承認の場合は空リスト。", default_factory=list)

class VideoPromptScene(BaseModel):
    scene_num: int = Field(description="シーン番号（1〜12）")
    motion: str = Field(description="画面内の動きの英語プロンプト (例: steam rising from the bowl)")
    camera: str = Field(description="カメラワークの英語プロンプト (例: slow pan right)")
    expression: str = Field(description="キャラクターの表情変化の英語プロンプト (例: subtle smile)")
    environment: str = Field(description="環境光や周囲の動きの英語プロンプト (例: warm izakaya lighting flickering)")
    negative_prompt: str = Field(description="動画生成用の英語ネガティブプロンプト。不要な場合は '-' を指定", default="-")

class VideoPromptOutput(BaseModel):
    scenes: List[VideoPromptScene] = Field(description="シーン1から12までのプロンプト", min_items=12, max_items=12)

class BGMPrompt(BaseModel):
    pattern: str = Field(description="'A' (和風) または 'B' (ピアノ・エモーショナル)")
    style_prompt: str = Field(description="Suno AI用の英語スタイルプロンプト（400-600文字程度）")

class BGMPromptOutput(BaseModel):
    prompts: List[BGMPrompt] = Field(description="パターンAとパターンBの2つのプロンプト", min_items=2, max_items=2)

class YouTubeTitleCandidate(BaseModel):
    angle: str = Field(description="タイトルのアプローチ（例: 'Number + Region'）")
    title: str = Field(description="タイトル案（必ず '孤独のグルメ風' を末尾に含める）")
    reason: str = Field(description="なぜこのエピソードに合っているかの理由")

class YouTubeMetadataOutput(BaseModel):
    titles: List[YouTubeTitleCandidate] = Field(description="タイトル候補3案", min_items=3, max_items=3)
    recommended_title: str = Field(description="推奨するタイトル（titlesの中から選択）")
    description: str = Field(description="概要欄のテキスト（日本語）")
    thumbnail_prompt: str = Field(description="サムネイル生成用の英語プロンプト（約80語）")
    tags: List[str] = Field(description="YouTube用のタグ（10個）", min_items=10, max_items=10)
