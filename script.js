const expressionDisplay = document.getElementById('expression');
const resultDisplay = document.getElementById('result');
const buttons = document.querySelectorAll('.btn');

let currentExpression = '0';
let resultValue = '0';

function sanitizeExpression(value) {
  return value.replace(/×/g, '*').replace(/÷/g, '/');
}

function updateDisplay() {
  expressionDisplay.textContent = currentExpression || '0';
  resultDisplay.textContent = resultValue || '0';
}

function isOperator(value) {
  return ['+', '-', '*', '/'].includes(value);
}

function appendValue(value) {
  if (currentExpression === '0' && !isOperator(value) && value !== '.') {
    currentExpression = value;
    resultValue = value;
    return;
  }

  if (value === '.' && /\d*\.\d*$/.test(currentExpression) === false) {
    const lastNumber = currentExpression.split(/[+\-*/]/).at(-1);
    if (lastNumber.includes('.')) {
      return;
    }
  }

  if (isOperator(value)) {
    const previous = currentExpression[currentExpression.length - 1];
    if (isOperator(previous)) {
      currentExpression = currentExpression.slice(0, -1) + value;
      resultValue = value;
      return;
    }
  }

  currentExpression += value;
  resultValue = value;
  updateDisplay();
}

function calculate() {
  if (!currentExpression || currentExpression === '0') {
    return;
  }

  const raw = sanitizeExpression(currentExpression);
  if (!/^[0-9+\-*/.() ]+$/.test(raw)) {
    resultValue = 'Error';
    updateDisplay();
    return;
  }

  try {
    const computed = Function(`"use strict"; return (${raw})`)();
    if (!Number.isFinite(computed)) {
      throw new Error('Invalid math');
    }
    const normalized = Number.isInteger(computed) ? computed.toString() : Number(computed.toFixed(10)).toString();
    resultValue = normalized;
    currentExpression = normalized;
    updateDisplay();
  } catch (error) {
    resultValue = 'Error';
    updateDisplay();
  }
}

function clearAll() {
  currentExpression = '0';
  resultValue = '0';
  updateDisplay();
}

function deleteLast() {
  if (currentExpression.length <= 1) {
    clearAll();
    return;
  }

  currentExpression = currentExpression.slice(0, -1);
  resultValue = currentExpression;
  updateDisplay();
}

function applyPercent() {
  const normalized = sanitizeExpression(currentExpression);
  if (!normalized || normalized === '0') {
    return;
  }

  try {
    const computed = Function(`"use strict"; return (${normalized}) / 100`)();
    if (!Number.isFinite(computed)) {
      throw new Error('Invalid percent');
    }
    currentExpression = Number.isInteger(computed) ? computed.toString() : Number(computed.toFixed(10)).toString();
    resultValue = currentExpression;
    updateDisplay();
  } catch (error) {
    resultValue = 'Error';
    updateDisplay();
  }
}

buttons.forEach((button) => {
  button.addEventListener('click', () => {
    const action = button.dataset.action;
    const value = button.dataset.value;

    if (action === 'clear') {
      clearAll();
      return;
    }

    if (action === 'delete') {
      deleteLast();
      return;
    }

    if (action === 'percent') {
      applyPercent();
      return;
    }

    if (action === 'equals') {
      calculate();
      return;
    }

    appendValue(value);
  });
});

document.addEventListener('keydown', (event) => {
  const { key } = event;
  if (/^[0-9]$/.test(key)) {
    appendValue(key);
  } else if (['+', '-', '*', '/'].includes(key)) {
    appendValue(key);
  } else if (key === '.') {
    appendValue('.');
  } else if (key === 'Enter' || key === '=') {
    calculate();
  } else if (key === 'Backspace') {
    deleteLast();
  } else if (key.toLowerCase() === 'c') {
    clearAll();
  }
});

updateDisplay();
