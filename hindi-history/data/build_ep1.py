"""One-off fixture builder: reconstruct data/ep1.json from the REAL Phase-1 Gemini
output produced at 10:20 for "The Founding of Rome". Used only because the shared
Gemini free-tier daily quota (20 req/day) is currently exhausted, so we can test
Phase 2 against genuine Phase-1 data without another API call.
"""
import json
from pathlib import Path

scenes = [
    ("नमस्ते दोस्तों, इतिहास के पन्नों में आपका फिर से स्वागत है. आज हम बात करेंगे एक ऐसी महान सभ्यता की, जिसने सदियों तक दुनिया को प्रभावित किया – रोम की. लेकिन क्या आप जानते हैं कि इस विशाल साम्राज्य की शुरुआत कैसे हुई? इसकी कहानी किसी परीकथा से कम नहीं है, जिसमें देवता हैं, राजा हैं और एक भयानक भेड़िया भी.",
     "An ancient map of the Italian peninsula, with a glowing, mythical aura around the region where Rome would be. Emphasize an epic, storytelling mood. Ancient Roman aesthetic."),
    ("कहानी शुरू होती है प्राचीन लातियम में, जहाँ अल्बा लोंगा नाम का एक शहर था. यहाँ के राजा थे नूमिटर, पर उनके धोखेबाज भाई अमुलीयस ने उन्हें गद्दी से हटा दिया और उनकी बेटी रिया सिल्विया को वेस्ता देवी के मंदिर में पुजारी बना दिया, ताकि वह कभी माँ न बन सके और नूमिटर का कोई वारिस न हो.",
     "A grand, ancient city of Alba Longa, with classical Roman-style architecture. Inside a temple, a young, sad Vestal Virgin (Rhea Silvia) in white robes is performing rituals, looking conflicted. An older, stern man (Amulius) watches from a distance."),
    ("पर होनी को कौन टाल सकता है? रिया सिल्विया को युद्ध के देवता मार्स से प्यार हो गया और उनके दो जुड़वां बेटे हुए – रोमुलस और रेमुस. जब अमुलीयस को यह बात पता चली, तो वह क्रोधित हो उठा. उसने रिया सिल्विया को कैद कर लिया और बच्चों को एक टोकरी में रखकर तिबेर नदी में फेंक देने का आदेश दिया.",
     "A dramatic scene. Rhea Silvia, looking distraught, holds two infant twins. The god Mars, in warrior attire, subtly appears as a glowing, protective figure behind her. In the foreground, a guard is taking the children away to be put in a basket."),
    ("लेकिन बच्चों की किस्मत में कुछ और ही लिखा था. नदी की धारा बच्चों को बहाकर किनारे ले आई, जहाँ एक मादा भेड़िया (शे-वुल्फ) ने उन्हें देखा. उस भेड़िया ने उन नवजात शिशुओं को अपना दूध पिलाया और उनकी जान बचाई, जैसे वो उसके अपने बच्चे हों. यह दृश्य वाकई चौंकाने वाला था.",
     "A majestic she-wolf (Lupa Capitolina style) suckling two human infant twins (Romulus and Remus) by the reedy banks of the Tiber River. The setting is wild and natural, with ancient trees. Warm, miraculous light."),
    ("कुछ समय बाद, एक चरवाहे, फौस्टुलस, को ये बच्चे मिले. उसने और उसकी पत्नी लारेन्सिया ने इन बच्चों को अपना लिया और उन्हें अपने बच्चों की तरह पाला. रोमुलस और रेमुस बड़े होकर बहादुर और ताकतवर युवा बने, जिनमें नेतृत्व करने की अद्भुत क्षमता थी.",
     "A rustic hut or small farm. A kind shepherd (Faustulus) and his wife (Laurentia) are lovingly raising the two young boys (Romulus and Remus), who are now active and strong children, playing with sheep and a dog. Simple, rural ancient Roman clothing."),
    ("धीरे-धीरे उन्हें अपनी असली पहचान और अपने दादा नूमिटर के साथ हुए अन्याय का पता चला. उन्होंने अपनी सेना इकट्ठा की, अमुलीयस को मारकर गद्दी से हटाया और नूमिटर को फिर से राजा बनाया. अब, उनके सामने एक नए शहर को बसाने की चुनौती थी.",
     "Two strong, young warrior brothers (Romulus and Remus), leading a small, determined band of rustic fighters. They are overthrowing the tyrannical Amulius in a palace courtyard, restoring their elderly grandfather, Numitor, to his throne. Action-oriented, ancient Roman era."),
    ("लेकिन शहर कहाँ बनाया जाए, इस बात पर दोनों भाइयों में मतभेद हो गया. रोमुलस पैलेटाइन पहाड़ी पर शहर बसाना चाहते थे, जबकि रेमुस अवनटाइन पहाड़ी को पसंद करते थे. इस बात को लेकर दोनों में झगड़ा इतना बढ़ा कि एक दिन रेमुस की मृत्यु हो गई. कुछ कहानियों के अनुसार, रोमुलस ने ही गुस्से में उन्हें मार दिया था.",
     "A dramatic and somber scene. Romulus stands over the fallen body of Remus on a desolate, hilly landscape, with a newly dug furrow marking the city's boundary in the background. The mood is tragic, reflecting the first fratricide of Rome's founding."),
    ("रेमुस की मृत्यु के बाद, रोमुलस ने 21 अप्रैल 753 ईसा पूर्व को पैलेटाइन पहाड़ी पर नए शहर की नींव रखी, जिसका नाम उन्होंने अपने नाम पर 'रोमा' यानी रोम रखा. उन्होंने खुद को इस शहर का पहला राजा घोषित किया.",
     "Romulus, now a king, wearing a simple toga and crown, stands proudly on the Palatine Hill. In the background, early, rudimentary walls of Rome are being built. The sky is clear, symbolizing a new beginning, 753 BC."),
    ("शुरुआत में रोम में जनसंख्या कम थी, खासकर महिलाओं की. इसलिए रोमुलस ने पड़ोसी सबाइन जनजाति की महिलाओं का अपहरण करने की योजना बनाई, जिसे 'द रेप ऑफ द सबाइन विमेन' के नाम से जाना जाता है. इससे सबाइन और रोम के बीच युद्ध हुआ, लेकिन अंततः शांति स्थापित हुई और दोनों संस्कृतियाँ एक हो गईं.",
     "A dynamic and chaotic scene depicting the 'Rape of the Sabine Women.' Roman men are carrying off Sabine women amidst a festival setting. There is a mix of fear and struggle, but also a sense of historical narrative rather than pure violence. Early Roman and Sabine attire."),
    ("रोमुलस ने रोम के लिए कानून बनाए, एक सीनेट की स्थापना की और शहर को एक मजबूत आधार दिया. उन्होंने लगभग 37 साल तक शासन किया और फिर एक दिन रहस्यमय तरीके से गायब हो गए, जिसके बाद उन्हें 'क्विरिनस' नामक देवता के रूप में पूजा जाने लगा.",
     "Romulus, older and wiser, sitting on a simple throne, addressing the newly formed Roman Senate. The senators are listening intently. A sense of law and order being established. The background shows early Roman public buildings. Later, a subtle transition to a celestial, divine image of Quirinus."),
    ("और इस तरह, एक भेड़िये द्वारा पाले गए और देवताओं के आशीर्वाद से बने इस शहर ने आगे चलकर दुनिया के सबसे बड़े साम्राज्यों में से एक की नींव रखी. रोम की यह कहानी हमें सिखाती है कि कैसे विपरीत परिस्थितियों में भी एक महान शुरुआत हो सकती है, और कैसे एक छोटे से बीज से एक विशाल वटवृक्ष जन्म लेता है. अगली बार फिर मिलेंगे एक नई कहानी के साथ, तब तक के लिए नमस्कार!",
     "A panoramic view of the vast Roman Empire stretching across Europe, Africa, and Asia, with iconic Roman structures like the Colosseum and aqueducts visible in the foreground. The image should convey the scale and grandeur of the empire that grew from humble beginnings, with a subtle overlay of the she-wolf and twins."),
]

episode = {
    "title": "रोम की कहानी: भेड़ियों ने पाला, देवताओं ने बनाया! | Rome History in Hindi",
    "description": "आज हम आपको ले चलेंगे एक ऐसी नगरी की शुरुआत की कहानी सुनाने, जिसने पूरी दुनिया पर राज किया. कैसे दो जुड़वां भाइयों, रोमुलस और रेमुस ने एक भयंकर भेड़िये के साए में पलकर रोम शहर की नींव रखी? यह सिर्फ एक शहर की नहीं, बल्कि एक साम्राज्य की दास्तान है.",
    "tags": ["रोम की कहानी", "रोमुलस और रेमुस", "प्राचीन रोम", "रोम का इतिहास",
             "Roman Mythology", "History of Rome", "Ancient Civilizations", "History in Hindi"],
    "full_script": "\n\n".join(t for t, _ in scenes),
    "scenes": [
        {"scene_number": i, "text": t, "image_prompt_hint": h}
        for i, (t, h) in enumerate(scenes, start=1)
    ],
}

out = Path(__file__).resolve().parent / "ep1.json"
out.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {out} with {len(scenes)} scenes")
