import random as _rand
import asyncio
import logging
from datetime import datetime
from engine.tools.weather_engine import fetch_weather_snapshot, _LOCATION_NAME

log = logging.getLogger("jarvis.greeting")


_greeted_since_boot = False

# Lời chào startup là văn bản cố định (không qua LLM), ghép ngẫu nhiên từ nhiều
# mảnh để mỗi lần mở máy nghe một khác. Mỗi khung giờ có:
#   greet    — câu chào (khẳng định)
#   care     — quan tâm, động viên (khẳng định)
#   remind   — nhắc một việc cụ thể nên làm (khẳng định)
#   followup — câu hỏi DUY NHẤT của cả lời chào, luôn đứng cuối
# Emoji chỉ để hiển thị; tts_manager tự lọc emoji trước khi đọc.
# `day` là mặc định sáng/tối khi nguồn thời tiết không cho biết.
_SLOTS = (
    {
        "start": 0, "end": 5, "day": False,
        "emoji": ("🌙", "🌌", "✨", "🌃"),
        "greet": (
            "Đêm khuya rồi mà ngài vẫn còn thức.",
            "Đã qua nửa đêm rồi, chào ngài.",
            "Giờ này mọi người đã ngủ cả, chỉ còn ngài và tôi.",
            "Khuya lắm rồi, tôi vẫn đang trực cùng ngài.",
            "Chào ngài, một ngày mới đã sang từ lúc nào không hay.",
        ),
        "care": (
            "Tôi hơi lo cho sức khỏe của ngài khi thức muộn thế này.",
            "Ngài đã vất vả cả ngày rồi, đừng ép bản thân quá sức nhé.",
            "Dù việc gấp đến đâu, sức khỏe của ngài vẫn quan trọng hơn.",
            "Mong ngài xong việc sớm để còn kịp nghỉ ngơi.",
        ),
        "remind": (
            "Ngài nhớ hạ bớt độ sáng màn hình cho đỡ mỏi mắt nhé.",
            "Nếu đói, ngài chỉ nên ăn nhẹ thôi, đừng uống thêm cà phê.",
            "Ngài nhớ uống chút nước ấm và đứng dậy vươn vai một chút.",
            "Xong việc là ngài nên đi ngủ ngay để sáng mai còn tỉnh táo.",
        ),
        "followup": (
            "Có việc gấp nào cần tôi xử lý giúp để ngài nghỉ sớm hơn không?",
            "Ngài cần tôi hỗ trợ gì trong lúc này không?",
            "Tôi có thể làm gì để ngài xong việc nhanh hơn không?",
        ),
    },
    {
        "start": 5, "end": 7, "day": True,
        "emoji": ("🌅", "🌄", "☀️", "🐦"),
        "greet": (
            "Chào buổi sáng sớm, ngài dậy sớm thật đấy.",
            "Trời vừa hửng sáng, chào ngài.",
            "Chào ngài, một ngày mới lại bắt đầu.",
            "Sáng tinh mơ rồi, chúc ngài khởi đầu ngày mới thật tươi tắn.",
            "Chào buổi sớm, không khí giờ này thật dễ chịu.",
        ),
        "care": (
            "Mong ngài đã có một giấc ngủ ngon.",
            "Chúc ngài một ngày mới nhiều năng lượng và thật suôn sẻ.",
            "Sáng sớm là lúc đầu óc minh mẫn nhất, mong mọi việc hôm nay của ngài đều thuận lợi.",
            "Tôi hy vọng hôm nay sẽ là một ngày thật nhẹ nhàng với ngài.",
        ),
        "remind": (
            "Ngài nhớ uống một ly nước ấm cho cơ thể tỉnh táo nhé.",
            "Đừng bỏ bữa sáng nhé ngài, nó giữ sức cho cả buổi.",
            "Nếu có thời gian, vài phút giãn cơ sẽ giúp ngài khỏe khoắn hơn.",
            "Ngài nhớ ăn sáng trước rồi hãy uống cà phê cho đỡ hại dạ dày nhé.",
        ),
        "followup": (
            "Hôm nay ngài muốn bắt đầu từ việc gì?",
            "Ngài có muốn tôi chuẩn bị gì cho ngày hôm nay không?",
            "Ngài cần tôi hỗ trợ gì cho buổi sáng này không?",
        ),
    },
    {
        "start": 7, "end": 11, "day": True,
        "emoji": ("☀️", "🌤️", "☕", "✨"),
        "greet": (
            "Chào buổi sáng, thưa ngài.",
            "Buổi sáng tốt lành, ngài.",
            "Chào ngài, chúc ngài một buổi sáng làm việc thật hiệu quả.",
            "Xin chào ngài, tôi đã sẵn sàng cho một buổi sáng bận rộn.",
            "Chào ngài, mong buổi sáng hôm nay của ngài suôn sẻ.",
        ),
        "care": (
            "Mong mọi việc sáng nay của ngài đều trôi chảy.",
            "Chúc ngài giữ được sự tập trung và tinh thần thoải mái.",
            "Buổi sáng là lúc làm việc hiệu quả nhất, mong ngài tận dụng thật tốt.",
            "Tôi tin hôm nay ngài sẽ hoàn thành tốt những gì đã định.",
        ),
        "remind": (
            "Ngài nhớ uống đủ nước, đừng chỉ uống cà phê nhé.",
            "Cứ khoảng một tiếng, ngài nên đứng dậy đi lại vài phút.",
            "Ngài nhớ cho mắt nghỉ, thỉnh thoảng nhìn ra xa chừng hai mươi giây nhé.",
            "Ngài nhớ ngồi thẳng lưng để đỡ mỏi vai gáy nhé.",
        ),
        "followup": (
            "Ngài cần tôi hỗ trợ gì không?",
            "Có việc gì cần tôi xử lý giúp ngài lúc này không?",
            "Hôm nay ngài muốn tôi bắt tay vào việc gì trước?",
        ),
    },
    {
        "start": 11, "end": 13, "day": True,
        "emoji": ("🍱", "🌞", "🍜", "☀️"),
        "greet": (
            "Chào buổi trưa, thưa ngài.",
            "Giữa trưa rồi, nửa ngày đã trôi qua.",
            "Buổi trưa tốt lành, cũng đến giờ nghỉ ngơi một chút rồi.",
            "Chào ngài, đã đến giờ nghỉ trưa.",
            "Trưa rồi, chào ngài.",
        ),
        "care": (
            "Ngài đã làm việc cả buổi sáng, giờ là lúc nạp lại năng lượng.",
            "Mong ngài có một bữa trưa ngon miệng và thư thái.",
            "Nửa ngày đã qua, mong mọi việc của ngài đều ổn cả.",
            "Công việc có thể đợi, còn sức khỏe của ngài thì không.",
        ),
        "remind": (
            "Ngài nhớ ăn trưa đầy đủ, đừng bỏ bữa kẻo hại dạ dày.",
            "Sau bữa trưa, ngài nên chợp mắt mười lăm phút cho chiều tỉnh táo.",
            "Ngài nhớ rời màn hình khi ăn cho mắt được nghỉ nhé.",
            "Ngài nhớ uống thêm nước sau bữa trưa nhé.",
        ),
        "followup": (
            "Trước khi nghỉ trưa, ngài có việc gì cần tôi làm không?",
            "Ngài cần tôi hỗ trợ gì không?",
            "Có việc gì ngài muốn tôi xử lý trong lúc ngài nghỉ trưa không?",
        ),
    },
    {
        "start": 13, "end": 17, "day": True,
        "emoji": ("🌤️", "☕", "📋", "☀️"),
        "greet": (
            "Chào buổi chiều, thưa ngài.",
            "Buổi chiều tốt lành, ngài.",
            "Chào ngài, chúc ngài một buổi chiều làm việc thuận lợi.",
            "Chào ngài, hy vọng bữa trưa đã giúp ngài nạp đủ năng lượng.",
            "Xin chào ngài, buổi chiều đã bắt đầu rồi.",
        ),
        "care": (
            "Mong buổi chiều của ngài nhẹ nhàng và hiệu quả.",
            "Chỉ còn vài tiếng nữa thôi, mong ngài giữ vững phong độ.",
            "Tôi tin ngài sẽ xử lý gọn gàng mọi việc chiều nay.",
            "Mong ngài đừng quá áp lực, cứ từng việc một thôi.",
        ),
        "remind": (
            "Chiều dễ buồn ngủ, ngài nhớ uống nước và vươn vai vài phút nhé.",
            "Ngài nhớ đứng dậy đi lại một chút cho máu lưu thông.",
            "Nếu thấy mỏi mắt, ngài hãy nhắm mắt nghỉ một phút nhé.",
            "Ngài hạn chế cà phê sau ba giờ chiều để tối dễ ngủ hơn nhé.",
        ),
        "followup": (
            "Ngài cần tôi hỗ trợ gì cho buổi chiều này không?",
            "Có việc gì cần tôi xử lý giúp ngài không?",
            "Ngài muốn tôi lo phần việc nào trước?",
        ),
    },
    {
        "start": 17, "end": 19, "day": True,
        "emoji": ("🌇", "🌆", "🌅", "🍃"),
        "greet": (
            "Chào buổi xế chiều, ngày sắp kết thúc rồi.",
            "Chiều tà rồi, chào ngài.",
            "Hoàng hôn buông xuống, chào ngài.",
            "Chào ngài, một ngày làm việc sắp khép lại.",
            "Chào ngài, trời đã về chiều.",
        ),
        "care": (
            "Ngài đã làm việc chăm chỉ cả ngày rồi.",
            "Mong hôm nay là một ngày trọn vẹn với ngài.",
            "Việc chưa xong thì mai làm tiếp, ngài đừng để bản thân quá mệt.",
            "Cảm ơn ngài vì một ngày làm việc nhiều nỗ lực.",
        ),
        "remind": (
            "Ngài nhớ nghỉ mắt và thư giãn một chút nhé.",
            "Nếu ra đường giờ này, ngài nhớ đi cẩn thận vì đường khá đông.",
            "Ngài nhớ sắp xếp việc để nghỉ ngơi đúng giờ nhé.",
            "Ngài nên vận động nhẹ một chút sau cả ngày ngồi nhiều.",
        ),
        "followup": (
            "Còn việc gì cần tôi xử lý trước khi kết thúc ngày không, thưa ngài?",
            "Ngài cần tôi hỗ trợ gì thêm không?",
            "Ngài có muốn tôi ghi lại việc gì cho ngày mai không?",
        ),
    },
    {
        "start": 19, "end": 22, "day": False,
        "emoji": ("🌙", "🌆", "✨", "🏠"),
        "greet": (
            "Chào buổi tối, thưa ngài.",
            "Buổi tối tốt lành, ngài.",
            "Chào ngài, mong ngài có một buổi tối ấm áp.",
            "Tối rồi, chào ngài.",
            "Chào ngài, một ngày dài đã qua.",
        ),
        "care": (
            "Cảm ơn ngài đã làm việc chăm chỉ hôm nay.",
            "Buổi tối là của ngài, mong ngài được thư giãn thật thoải mái.",
            "Mong ngài có thời gian bên gia đình và làm điều mình thích.",
            "Sau một ngày dài, ngài xứng đáng được nghỉ ngơi.",
        ),
        "remind": (
            "Ngài nhớ ăn tối đầy đủ, đừng ăn quá muộn nhé.",
            "Ngài nên hạn chế nhìn màn hình để tối dễ ngủ hơn.",
            "Đi bộ nhẹ một chút sau bữa tối sẽ tốt cho ngài đấy.",
            "Ngài nhớ đi ngủ trước mười một giờ để giữ sức cho ngày mai nhé.",
        ),
        "followup": (
            "Ngài còn việc gì cần tôi hỗ trợ tối nay không?",
            "Có việc gì cần tôi xử lý giúp ngài lúc này không?",
            "Ngài có muốn tôi chuẩn bị gì cho ngày mai không?",
        ),
    },
    {
        "start": 22, "end": 24, "day": False,
        "emoji": ("🌙", "😴", "🌌", "💤"),
        "greet": (
            "Khuya rồi, ngài vẫn còn thức.",
            "Đêm đã khuya, chào ngài.",
            "Đã muộn rồi, tôi vẫn ở đây cùng ngài.",
            "Chào ngài, giờ này đã khá khuya rồi.",
            "Chào ngài, một ngày nữa sắp qua.",
        ),
        "care": (
            "Ngài đã vất vả cả ngày rồi, giờ nên để cơ thể nghỉ ngơi.",
            "Công việc ngày mai vẫn còn đó, sức khỏe của ngài mới là quan trọng nhất.",
            "Mong ngài có một giấc ngủ thật sâu và ngon.",
            "Tôi hơi lo khi ngài thức muộn thế này.",
        ),
        "remind": (
            "Ngài nhớ tắt bớt màn hình trước khi ngủ để dễ vào giấc nhé.",
            "Ngài nhớ đặt báo thức và sạc điện thoại trước khi ngủ nhé.",
            "Giờ này ngài không nên uống cà phê hay trà đặc nữa.",
            "Ngài cố gắng đi ngủ trước nửa đêm nhé.",
        ),
        "followup": (
            "Có việc gì gấp cần tôi xử lý trước khi ngài nghỉ không?",
            "Ngài cần tôi hỗ trợ gì trước khi đi ngủ không?",
            "Ngài có muốn tôi ghi lại việc gì cho ngày mai không?",
        ),
    },
)

# Câu thêm theo thứ trong tuần (weekday(): 0 = thứ Hai), chỉ dùng ban ngày.
_WEEKDAY_LINES = {
    0: ("Đầu tuần rồi, chúc ngài một tuần mới suôn sẻ.", "Tuần mới bắt đầu, mong ngài thật nhiều năng lượng."),
    4: ("Hôm nay thứ Sáu, sắp đến cuối tuần rồi.", "Cố lên ngài, mai là cuối tuần rồi."),
    5: ("Hôm nay cuối tuần, ngài nhớ dành thời gian cho bản thân nhé.", "Cuối tuần rồi, mong ngài có thời gian nghỉ ngơi."),
    6: ("Hôm nay Chủ nhật, mong ngài có một ngày thật thư thả.", "Chủ nhật rồi, ngài nhớ nạp lại năng lượng cho tuần mới nhé."),
}

_TIME_LINES = ("Bây giờ là {t}.", "Đồng hồ đang chỉ {t}.", "Lúc này là {t}.")

_WEATHER_LINES = (
    "Ngoài trời hiện {sky}{temp}.",  # {sky}: bỏ chữ "trời" đầu để không thành "ngoài trời hiện trời nắng"
    "Thời tiết {loc} lúc này {desc}{temp}.",
    "Hiện tại ở {loc} {desc}{temp}.",
)

_WEATHER_EMOJI = {
    "storm": "⛈️", "rain": "🌧️", "snow": "❄️", "haze": "😷", "fog": "🌫️",
}

# Lời nhắc theo thời tiết: (ban ngày, ban đêm). Khi có lời nhắc này thì bỏ câu
# nhắc chung của khung giờ, tránh nhắc hai việc liền nhau.
_SKY_TIPS = {
    "storm": (
        ("Ngài hạn chế ra ngoài và tránh chỗ trống trải nhé.", "Có giông sét, ngài nhớ rút phích các thiết bị không cần thiết nhé."),
        ("Ngài nhớ đóng kỹ cửa sổ nhé.", "Có giông sét, ngài nhớ rút phích các thiết bị không cần thiết nhé."),
    ),
    "rain": (
        ("Ngài ra ngoài nhớ mang theo ô hoặc áo mưa nhé.", "Đường có thể trơn, ngài đi lại cẩn thận nhé."),
        ("Ngài nhớ đóng cửa sổ và giữ ấm nhé.", "Mưa đêm dễ lạnh, ngài nhớ đắp chăn ấm nhé."),
    ),
    "snow": (("Ngài nhớ mặc thật ấm nhé.",), ("Ngài nhớ mặc thật ấm nhé.",)),
    "haze": (
        ("Không khí nhiều khói bụi, ngài ra ngoài nhớ đeo khẩu trang nhé.", "Bụi mịn khá nhiều, ngài nên hạn chế mở cửa sổ lâu nhé."),
        ("Không khí nhiều khói bụi, ngài nên đóng cửa sổ khi ngủ nhé.",),
    ),
    "fog": (
        ("Tầm nhìn hạn chế, ngài di chuyển chậm và cẩn thận nhé.",),
        ("Có sương, ngài nhớ giữ ấm cổ họng nhé.",),
    ),
}
_HOT_TIPS = ("Trời khá nóng, ngài nhớ uống đủ nước và tránh nắng gắt nhé.", "Nắng nóng dễ mệt, ngài nhớ bổ sung nước thường xuyên nhé.")
_COLD_TIPS = ("Trời se lạnh, ngài nhớ mặc thêm áo ấm nhé.", "Tiết trời hơi lạnh, ngài nhớ giữ ấm cơ thể nhé.")
_SUN_TIPS = ("Nắng khá gắt, ngài ra ngoài nhớ đội mũ và thoa kem chống nắng nhé.", "Trời nắng, ngài ra ngoài nhớ che chắn kỹ nhé.")
_HOT_C, _COLD_C = 34, 20

# Chờ thời tiết tối đa từng này giây sau khi câu chào đã được đọc; quá hạn thì bỏ
# qua để phần còn lại không bị kẹt sau mạng chậm.
_WEATHER_WAIT_SECONDS = 4.0


def _slot_for(hour: int) -> dict:
    for slot in _SLOTS:
        if slot["start"] <= hour < slot["end"]:
            return slot
    return _SLOTS[-1]


def _spoken_time(now) -> str:
    """'8 giờ 30 phút' — đọc tự nhiên hơn '08:30' khi qua TTS."""
    return f"{now.hour} giờ {now.minute} phút" if now.minute else f"{now.hour} giờ"


def _opening(now: datetime) -> str:
    slot = _slot_for(now.hour)
    parts = [_rand.choice(slot["emoji"]), _rand.choice(slot["greet"])]
    extra = _WEEKDAY_LINES.get(now.weekday())
    if extra and 5 <= now.hour < 19 and _rand.random() < 0.7:
        parts.append(_rand.choice(extra))
    parts.append(_rand.choice(_TIME_LINES).format(t=_spoken_time(now)))
    return " ".join(parts)


def _weather_sentence(snap, now: datetime) -> tuple[str, bool]:
    """(câu thời tiết, có lời nhắc hay không). Số liệu lấy nguyên từ nguồn; lời nhắc
    chỉ thêm khi thời tiết thật sự cần lưu ý."""
    if not snap or not snap.get("desc"):
        return "", False
    is_day = snap.get("is_day")
    if is_day is None:
        is_day = _slot_for(now.hour)["day"]
    kind, temp = snap.get("kind"), snap.get("temp")

    if kind == "clear":
        emoji = "☀️" if is_day else "🌙"
    elif kind == "cloudy":
        emoji = "⛅" if is_day else "☁️"
    else:
        emoji = _WEATHER_EMOJI.get(kind, "🌡️")

    body = _rand.choice(_WEATHER_LINES).format(
        desc=snap["desc"],
        sky=snap["desc"].removeprefix("trời "),
        loc=_LOCATION_NAME,
        temp=f", khoảng {temp} độ C" if temp is not None else "",
    )

    tips = ()
    if kind in _SKY_TIPS:
        tips = _SKY_TIPS[kind][0 if is_day else 1]
    elif temp is not None and temp >= _HOT_C and is_day:
        tips = _HOT_TIPS
    elif temp is not None and temp <= _COLD_C:
        tips = _COLD_TIPS
    elif kind == "clear" and is_day and 9 <= now.hour < 16:
        tips = _SUN_TIPS
    tip = _rand.choice(tips) if tips else ""
    return " ".join(p for p in (emoji, body, tip) if p), bool(tip)


def _closing(now: datetime, snap) -> list[str]:
    """Phần sau câu chào: thời tiết (+ nhắc), quan tâm, nhắc chung nếu thời tiết
    chưa nhắc gì, và cuối cùng là câu hỏi duy nhất."""
    slot = _slot_for(now.hour)
    weather, has_tip = _weather_sentence(snap, now)
    out = [weather] if weather else []
    out.append(_rand.choice(slot["care"]))
    if not has_tip:
        out.append(_rand.choice(slot["remind"]))
    out.append(_rand.choice(slot["followup"]))
    return out


def _compose(now: datetime, snap) -> list[str]:
    return [_opening(now)] + _closing(now, snap)


async def _fetch_weather_or_none():
    try:
        return await fetch_weather_snapshot()
    except Exception as e:
        log.warning(f"Greeting weather failed: {e}")
        return None


async def send_greeting(ws, history: list, safe_ws_send_json):
    """Lời chào startup cố định, stream như chat thường: từng câu vào VoiceStreamer
    (TTS đọc ngay câu đầu) và chữ hiện song song, không chờ cả đoạn."""
    global _greeted_since_boot
    # Chỉ chào 1 lần cho mỗi lần khởi động server — mọi kết nối WS sau đó
    # (reload trang, mở tab mới, rớt mạng rồi nối lại) đều bỏ qua.
    # ponytail: cờ tiến trình, không cần lưu trạng thái phía client.
    if _greeted_since_boot:
        return
    _greeted_since_boot = True

    await safe_ws_send_json(ws, {"type": "stream_start"})

    from engine.server.text_streamer import stream_text_smoothly
    from engine.server.voice_streamer import VoiceStreamer

    now = datetime.now()

    # Thời tiết chạy ngầm ngay từ đầu, câu chào không phải chờ nó.
    weather_task = asyncio.create_task(_fetch_weather_or_none())

    streamer = None
    lifecycle = None
    if not getattr(ws, "media_active", False):
        streamer = VoiceStreamer(ws)
        streamer.start()
        feed_done = asyncio.Event()

        async def _finish_speech():
            try:
                await feed_done.wait()
                await streamer.stop()  # đọc nốt các câu đã xếp hàng rồi mới đóng
            except asyncio.CancelledError:
                # User nói chen / tắt TTS: dừng cứng cả prefetch lẫn worker, nếu
                # không prefetch sẽ kẹt mãi trên audio_queue đầy.
                tasks = [t for t in (streamer.prefetch_task, streamer.worker_task) if t]
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                ws.tts_active = False
                raise

        lifecycle = asyncio.create_task(_finish_speech())
        ws.greeting_tts_task = lifecycle

        def _clear_greeting_tts_task(done_task):
            if getattr(ws, "greeting_tts_task", None) is done_task:
                ws.greeting_tts_task = None

        lifecycle.add_done_callback(_clear_greeting_tts_task)

    spoken: list[str] = []

    async def say(sentence: str):
        if streamer:
            await streamer.put(sentence)
        shown = sentence if not spoken else " " + sentence
        spoken.append(sentence)
        await stream_text_smoothly(ws, safe_ws_send_json, shown, word_delay=0.02)

    try:
        await say(_opening(now))

        try:
            snap = await asyncio.wait_for(weather_task, timeout=_WEATHER_WAIT_SECONDS)
        except asyncio.TimeoutError:
            log.info("Greeting weather timed out, skipping")
            snap = None
        for sentence in _closing(now, snap):
            await say(sentence)
        await safe_ws_send_json(ws, {"type": "stream_end"})
    except asyncio.CancelledError:
        if lifecycle:
            lifecycle.cancel()
            await asyncio.gather(lifecycle, return_exceptions=True)
        raise
    except Exception as e:
        log.warning(f"Greeting failed: {e}")
    finally:
        if not weather_task.done():
            weather_task.cancel()
        if lifecycle and not lifecycle.done():
            feed_done.set()
        if spoken:
            greeting = " ".join(spoken)
            history.append({"role": "assistant", "content": greeting})
            log.info(f"JARVIS: {greeting}")
