# -*- coding: utf-8 -*-
"""Обучение нашей нейросети-классификатора токсичности для модератора.

База: SberDevices/rubert-tiny2 (29M параметров, ~45 МБ) + русский датасет
токсичности SberDevices/russian_toxicity_dataset (116k комментариев).

Загрузка модели/датасета идёт через зеркало hf-mirror.com (HuggingFace
из РФ заблокирован). Обучение на CPU.

Результат: models/toxic_classifier/ — своя модель для src/toxicity.py
"""
import os

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_XET"] = "1"

import json
import random
import sys
import time

import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    get_scheduler,
)

MODEL_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "rubert-tiny2-base")  # скачана вручную через hf-mirror
DATASET_NAME = "molyalya/russian-toxicity-dataset"  # копия SberDevices-датасета на зеркале
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "toxic_classifier")
HARD_CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", "hard_cases.jsonl")
MAX_LEN = 96          # сообщения в чате короткие
BATCH_SIZE = 32
LR = 2e-5
SEED = 42

# Если веса уже есть — дообучаемся (resume), быстрее и сохраняем качество.
RESUME = os.path.isfile(os.path.join(OUT_DIR, "model.safetensors")) or os.path.isfile(os.path.join(OUT_DIR, "pytorch_model.bin"))
EPOCHS = int(os.getenv("FINETUNE_EPOCHS", "1" if RESUME else "2"))
MAX_SAMPLES = int(os.getenv("FINETUNE_SAMPLES", "8000" if RESUME else "30000"))
# Во сколько раз дублировать «сложные случаи» в обучении, чтобы модель их запомнила
HARD_REPEAT = int(os.getenv("FINETUNE_HARD_REPEAT", "10"))

random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)


class ToxDataset(Dataset):
    def __init__(self, texts, labels, tokenizer):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, i):
        enc = self.tokenizer(
            self.texts[i],
            truncation=True,
            max_length=MAX_LEN,
            padding="max_length",
        )
        return {
            "input_ids": torch.tensor(enc["input_ids"], dtype=torch.long),
            "attention_mask": torch.tensor(enc["attention_mask"], dtype=torch.long),
            "labels": torch.tensor(self.labels[i], dtype=torch.long),
        }


def main():
    t0 = time.time()
    print("1) Загружаю датасет из datasets/train.parquet ...", flush=True)
    import pandas as pd
    train_df = pd.read_parquet(os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", "train.parquet"))
    val_df = pd.read_parquet(os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", "validation.parquet"))
    print("   train:", train_df.shape, "validation:", val_df.shape, flush=True)
    print("   колонки:", list(train_df.columns), flush=True)
    print("   пример:", train_df.iloc[0].to_dict(), flush=True)

    # колонки могут называться по-разному — ищем текстовую и бинарную метку
    text_col = next(c for c in train_df.columns if c.lower() in ("comment", "text", "comment_text"))
    label_col = next(c for c in train_df.columns if c.lower() in ("toxic", "label", "is_toxic"))

    texts = [str(x) for x in train_df[text_col]]
    labels = [int(x) for x in train_df[label_col]]
    val_texts = [str(x) for x in val_df[text_col]]
    val_labels = [int(x) for x in val_df[label_col]]
    print("   toxic=1:", sum(labels), " toxic=0:", len(labels) - sum(labels), flush=True)

    # сбалансированная подвыборка
    pos_idx = [i for i, l in enumerate(labels) if l == 1]
    neg_idx = [i for i, l in enumerate(labels) if l == 0]
    half = MAX_SAMPLES // 2
    random.shuffle(pos_idx)
    random.shuffle(neg_idx)
    pick = pos_idx[:half] + neg_idx[:half]
    random.shuffle(pick)
    texts = [texts[i] for i in pick]
    labels = [labels[i] for i in pick]
    print(f"   подвыборка: {len(texts)} (pos={sum(labels)}, neg={len(labels)-sum(labels)})", flush=True)

    # наши «сложные случаи» (hard_cases.jsonl) — добавляем в обучение И валидацию
    hard = []
    if os.path.isfile(HARD_CASES):
        with open(HARD_CASES, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    hard.append(json.loads(line))
        print(f"   hard_cases.jsonl: {len(hard)} (pos={sum(1 for h in hard if h['label']==1)}, "
              f"neg={sum(1 for h in hard if h['label']==0)})", flush=True)
    for h in hard:
        texts.append(h["text"])
        labels.append(int(h["label"]))
        val_texts.append(h["text"])
        val_labels.append(int(h["label"]))
    # дублируем hard в обучающей выборке, чтобы они не затерялись в 8k примерах
    for h in hard:
        for _ in range(HARD_REPEAT - 1):
            texts.append(h["text"])
            labels.append(int(h["label"]))
    print(f"   итого train: {len(texts)}, val: {len(val_texts)}", flush=True)

    if RESUME:
        print("2) Дообучаюсь с текущих весов:", OUT_DIR, flush=True)
        tokenizer = AutoTokenizer.from_pretrained(OUT_DIR)
        model = AutoModelForSequenceClassification.from_pretrained(OUT_DIR)
    else:
        print("2) Загружаю модель", MODEL_NAME, "...", flush=True)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)
    model.train()
    print("   параметров:", sum(p.numel() for p in model.parameters()) // 1_000_000, "M", flush=True)

    train_ds = ToxDataset(texts, labels, tokenizer)
    val_ds = ToxDataset(val_texts, val_labels, tokenizer)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE)

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    num_steps = len(train_loader) * EPOCHS
    scheduler = get_scheduler("linear", optimizer=optimizer, num_warmup_steps=0, num_training_steps=num_steps)
    device = "cpu"
    model.to(device)

    print("3) Обучение ...", flush=True)
    step = 0
    for epoch in range(EPOCHS):
        model.train()
        total_loss = 0.0
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            out = model(**batch)
            loss = out.loss
            loss.backward()
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            total_loss += loss.item()
            step += 1
            if step % 100 == 0:
                el = time.time() - t0
                print(f"   epoch {epoch+1}/{EPOCHS} step {step}/{num_steps} "
                      f"loss {loss.item():.4f} ({el/60:.1f} мин)", flush=True)
        # валидация
        model.eval()
        preds, trues = [], []
        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                logits = model(**batch).logits
                preds += logits.argmax(-1).tolist()
                trues += batch["labels"].tolist()
        acc = accuracy_score(trues, preds)
        f1 = f1_score(trues, preds)
        print(f"   epoch {epoch+1} val: acc={acc:.4f} f1={f1:.4f}", flush=True)

    print("4) Сохраняю в", OUT_DIR, flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    model.save_pretrained(OUT_DIR)
    tokenizer.save_pretrained(OUT_DIR)
    print(f"Готово за {(time.time()-t0)/60:.1f} мин. Модель: {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
