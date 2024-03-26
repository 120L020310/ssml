# ssml
An interface to analysize SSML（XML） and generate the audio
此处以ssml为例，调用get_speak函数也可以解析<speak><\speak>为例的xml文件
提供了两个测试结果，对于voice类型采用现有音频，使用时可以将load_voice替换为自己的语音合成接口。load_audio也可自行修改
包含代码健壮性设计，对不匹配类型会给出相应警告信息。需要修改参数时，修改gen_audio,gen_voice等函数即可
