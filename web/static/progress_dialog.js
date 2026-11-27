/* Shared dialog for background work. An omitted percentage denotes unknown duration. */
window.createProgressDialog = (dialog) => {
  const title = dialog.querySelector('h2');
  const bar = dialog.querySelector('progress');
  const log = dialog.querySelector('[role="log"]');
  const close = dialog.querySelector('[data-progress-close]');
  close.onclick = () => dialog.close();

  return {
    open(label) {
      title.textContent = label;
      close.textContent = 'Fechar';
      log.replaceChildren();
      bar.removeAttribute('value');
      if (!dialog.open) dialog.showModal();
    },
    update({progress, messages}) {
      if (Number.isFinite(progress)) bar.value = progress;
      else bar.removeAttribute('value');
      const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 8;
      for (const message of messages.slice(log.childElementCount)) {
        const line = document.createElement('p');
        line.textContent = message;
        log.append(line);
      }
      if (atEnd) log.scrollTop = log.scrollHeight;
    },
    finish(label, onClose) {
      if (dialog.open) {
        close.textContent = label;
        dialog.addEventListener('close', onClose, {once: true});
      } else {
        onClose();
      }
    },
    close() { dialog.close(); },
  };
};
