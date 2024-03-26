import logging
import os
import re
import xml.etree.ElementTree as ET
import requests as requests
from pydantic import BaseModel
from enum import Enum
from typing import List, Optional, Dict
from loguru import logger
from pydantic_core import ValidationError
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError


class AudioType(str, Enum):
    silence = 'sil'  # silence
    audio = 'audio'  # url
    voice = 'voice'  # speech


class AudioPie(BaseModel):
    attr: Dict[str, str] = {}
    type: Optional[AudioType] = None
    """
        type=sil,attr='value'
        type=voice,attr='speaker','length','text'
        type=audio,attr='src','volume'
    """


class AudioContainer(BaseModel):
    background: Optional[AudioPie] = None
    audio_pies: List[AudioPie] = []


def load_voice(speaker, length, text):
    if speaker == "default_speaker" and length == "default_length":
        return AudioSegment.from_file("./audios/default.mp3")
    return AudioSegment.from_file("./audios/voice.mp3")


def load_audio(src, volume):
    save_path = os.path.join("./audios", src)
    if os.path.exists(save_path):
        # 如果本地文件存在，直接返回文件内容
        # print("save_path:", save_path)
        try:
            audio = AudioSegment.from_file(save_path)
        except CouldntDecodeError as e:
            # 处理解码失败的情况
            logger.debug(f"文件{save_path}解码失败: {e}")
            return 0
        return audio + (1 - float(volume.rstrip("%")) / 100) * (-20)
    else:
        # 如果本地文件不存在，则从指定 URL 下载文件
        try:
            response = requests.get("https://downsc.chinaz.net/Files/DownLoad/sound1/201805/10077.mp3")

            if response.status_code == 200:
                # 下载成功，保存文件并返回文件内容
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                audio = AudioSegment.from_file(save_path)
                return audio + (1 - float(volume.rstrip("%")) / 100) * (-20)
            else:
                # 下载失败，返回空字符串
                logger.debug("Download failed.")
                return 0
        except CouldntDecodeError as e:
            # 处理解码失败的情况
            logger.debug(f"文件解码失败: {e}")


def gen_audio(audio):
    try:
        src = audio.attr['src']
        volume = audio.attr['volume']
        return load_audio(src, volume)
    except KeyError as e:
        logger.debug(f"audio标签内容错误，{e}")
        return 0


def gen_voice(voice):
    try:
        speaker = voice.attr['speaker']
        length = voice.attr['length']
        text = voice.attr['text']
        return load_voice(speaker, length, text)
    except KeyError as e:
        logger.debug(f"voice标签内容错误，{e}")
        return 0


def gen_sil(sil):
    try:
        time = sil.attr['duration_ms']
        silence = AudioSegment.silent(duration=int(time))
        return silence
    except KeyError as e:
        logger.debug(f"silence标签内容错误，{e}")
        return 0


def gen_background(container):
    try:
        src = container.background.attr['src']
        volume = container.background.attr['volume']
        return load_audio(src, volume)
    except KeyError as e:
        logger.debug(f"backgroundaudio存在参数错误,{e}")
        return 0


def gen_audiopies(audio_pies):
    overlay_audio = 0
    for audio in audio_pies:
        if audio.type == AudioType.audio:
            overlay_audio = overlay_audio + gen_audio(audio)
        elif audio.type == AudioType.voice:
            overlay_audio = overlay_audio + gen_voice(audio)
        else:
            overlay_audio = overlay_audio + gen_sil(audio)
    combined_audio = overlay_audio
    return combined_audio


def parse_xml_to_containers(xml_content):
    root = ET.fromstring(xml_content)
    containers = []

    for child in root:
        if child.tag == 'backgroundaudio':
            background = AudioPie(attr=child.attrib, type=AudioType.audio)
            audio_pies = parse_children(child)
            containers.append(AudioContainer(background=background, audio_pies=audio_pies))
        else:
            audio_pies = parse_element(child)
            containers.extend(audio_pies)

    return containers


# 解析非backgroundaudio元素
def parse_element(element):
    if element.tag in {'voice', 'audio', 'silence'}:
        audio_pie = AudioPie(attr=element.attrib, type=AudioType[element.tag])
        if element.text and element.text.strip():
            audio_pie.attr['text'] = element.text.strip()
        return [AudioContainer(background=None, audio_pies=[audio_pie])]
    return []


# 解析backgroundaudio下的子元素
def parse_children(background_element):
    audio_pies = []
    for child in background_element:
        audio_pies.extend(parse_element(child))
    return [pie.audio_pies[0] for pie in audio_pies]


def get_speak(xml_content):
    containers = parse_xml_to_containers(xml_content)
    # 打印结果
    speak = []
    for container in containers:
        speak.append(container)
    return speak


def extract_text_pydantic(ssml):
    # 使用正则表达式查找所有 <speak> 标签之外的文本内容和 <speak> 标签内的内容
    matches = re.finditer(r'<speak>(.*?)</speak>|.*?(?=<speak>|$)', ssml, re.DOTALL)
    speak_list = []
    texts = []
    for match in matches:
        if match.group(1):  # 如果匹配到了 <speak> 标签内的内容
            texts.append("<speak>" + match.group(1) + "</speak>")
        else:  # 如果匹配到了 <speak> 标签之外的文本内容
            texts.append(match.group().strip())
    texts = [text for text in texts if text.strip()]
    for i, t in enumerate(texts):
        if "<speak>" in t:
            texts[i] = get_speak(t)
        else:
            ts = texts[i].replace('\n', '').strip()
            container = AudioContainer(background=None, audio_pies=[])
            voice = AudioPie(
                attr={'speaker': 'default_speaker', 'length': 'default_length',
                      'text': ts},
                type='voice')
            container.audio_pies.append(voice)
            texts[i] = [container]
    # 去除空字符串并返回
    return texts


def merge(ssmls):
    ssml_audio = None
    for i, item in enumerate(ssmls):
        if item is not None and len(item) != 0:
            # if isinstance(item, list) and item:
            speak_audio = None
            for ind, container in enumerate(item):
                combined_audio = gen_audiopies(container.audio_pies)
                if container.background is not None:
                    background_audio = gen_background(container)
                    try:
                        combined_audio = background_audio.overlay(combined_audio)
                    except AttributeError as e:
                        logger.debug(f"background合成失败，{e}")
                speak_audio = combined_audio if speak_audio is None else speak_audio + combined_audio
            if speak_audio != 0:
                logger.info("audio " + str(i) + " has generated successfully!")
            else:
                logger.debug("audio " + str(i) + " has generated failed~~")
            ssml_audio = speak_audio if ssml_audio is None else ssml_audio + speak_audio
        else:
            logger.debug("audio " + str(i) + " has generated failed~~")
    return ssml_audio


if __name__ == '__main__':
    # test = """
    # 111111111111111111hhhhhhhhhhhhhhhhh
    # <speak>
    #     <backgroundaudio src="bird.mp3" volume="100%">
    #         <voice speaker="Alice" length="1.2">
    #         Hello, this is a test.
    #         </voice>
    #         <audio src="wolf.mp3" volume="70%">
    #         </audio> <!-- 添加了正确的闭合标签 -->
    #         <silence duration_ms="500"></silence>
    #         <voice speaker="Jane" length="1.0">
    #         Soga,I hope so.
    #         </voice>
    #     </backgroundaudio>
    # </speak>
    # 哈哈哈哈哈哈哈哈哈哈哈哈哈哈
    # <speak>
    #     <backgroundaudio src="music.mp3" volume="100%">
    #         <voice speaker="Jane" length="1.0">
    #         Hello, this is a test in background.
    #         </voice>
    #     </backgroundaudio>
    #     <voice speaker="Alice" length="1.2">
    #     Hello, this is a test.
    #     </voice>
    #     <audio src="sound.mp3" volume="80%">
    #     </audio>
    #     <silence duration_ms="500"></silence>
    #      <!-- 添加了正确的闭合标签 -->
    # </speak>
    # 111111111111111111hhhhhhhhhhhhhhhhh
    # """
    #
    #
    # result = extract_text_pydantic(test)
    # print(merge(result))
    # ssml_audio = merge(result)
    # # print(get_attr_pydantic(result))
    # try:
    #     ssml_audio.export("ssml_audio" + ".mp3", format="mp3")
    #     logger.info("ssml_audio has generated successfully!")
    # except AttributeError as e:
    #     logger.debug(f"验证错误: {e}   合成错误")


    test0 = """
    <speak>
        <backgroundaudio srcs="bird.mp3" volume="100%">
            <voice speaker="Alice" length="1.2">
            Hello, this is a test.
            </voice>
            <audio src="wolf.mp3" volume="70%">
            </audio> <!-- 添加了正确的闭合标签 -->
            <silence duration_ms="5000"></silence>
            <voice speaker="Jane" length="1.0">
            Soga,I hope so.
            </voice>
        </backgroundaudio>
    </speak>
    哈哈哈哈哈哈哈哈哈哈哈哈哈哈
    <speak>
        <backgroundaudio src="music.mp3" volume="100%">
            <voice speaker="Jane" length="1.0">
            Hello, this is a test in background.
            </voice>
        </backgroundaudio>
        <voice speaker="Alice" length="1.2">
        Hello, this is a test.
        </voice>
        <audio src="sound.mp3" volume="80%">
        </audio>
        <silence duration_mss="500"></silence>
         <!-- 添加了正确的闭合标签 -->
    </speak>
    """
    result0 = extract_text_pydantic(test0)
    print(result0)
    print(merge(result0))
    ssml_audio = merge(result0)
    try:
        ssml_audio.export("ssml_audio" + ".mp3", format="mp3")
        logger.info("ssml_audio has generated successfully!")
    except AttributeError as e:
        logger.debug(f"验证错误: {e}   合成错误")
