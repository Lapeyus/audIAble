from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.probability import FreqDist
import string
import heapq
import os


def summarize_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        text = file.read()

    sentences = sent_tokenize(text)
    words = word_tokenize(text)
    words = [word.lower() for word in words]
    words = [word for word in words if word not in string.punctuation]

    frequency = FreqDist(words)
    num_sentences = int(len(sentences) * 0.2)

    relevance = {i: sum(frequency[word] for word in word_tokenize(sentence.lower()) if word not in string.punctuation) for i, sentence in enumerate(sentences)}
    top_sentences = heapq.nlargest(num_sentences, relevance, key=relevance.get)
    summary_sentences = [sentences[i] for i in sorted(top_sentences)]
    summary_text = ' '.join(summary_sentences)

    return summary_text


def process_files_in_directory(input_directory_path, output_directory_path):
    try:
        # Crear el directorio de salida si no existe
        os.makedirs(output_directory_path, exist_ok=True)

        for filename in os.listdir(input_directory_path):
            if filename.endswith('.txt'):
                filepath = os.path.join(input_directory_path, filename)
                summary_text = summarize_text(filepath)

                # Guarda el texto resumido en el directorio de salida con una nueva extensión ".res"
                output_filepath = os.path.join(output_directory_path, filename.rstrip('.txt') + '.res')
                with open(output_filepath, 'w', encoding='utf-8') as output_file:
                    output_file.write(summary_text)

        print('All files have been processed and summaries saved with .res extension.')
    except Exception as e:
        print(f'An error occurred: {e}')


# Especifica la ruta de la carpeta que contiene los archivos .txt que deseas procesar
process_files_in_directory('./cap1', './res')
