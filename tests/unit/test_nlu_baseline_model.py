from pathlib import Path

from core.nlu.baseline_intent_model import NaiveBayesIntentModel


def test_naive_bayes_intent_model_fit_predict_roundtrip(tmp_path: Path):
    texts = [
        "safari ac",
        "chrome ac",
        "not dosyasi yaz",
        "masaustune dosya yaz",
        "kapat safari",
    ]
    labels = [
        "open_app",
        "open_app",
        "write_file",
        "write_file",
        "close_app",
    ]
    model = NaiveBayesIntentModel().fit(texts, labels)
    pred, conf = model.predict("safariyi ac")
    assert pred == "open_app"
    assert conf > 0.0

    out = model.save(tmp_path / "nb.json")
    loaded = NaiveBayesIntentModel.load(out)
    pred2, conf2 = loaded.predict("not yaz")
    assert pred2 in {"write_file", "open_app", "close_app"}
    assert conf2 >= 0.0
