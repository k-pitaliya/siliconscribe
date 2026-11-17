import '@testing-library/jest-dom'

// jsdom does not implement scrollIntoView; components call it to follow new chat messages.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
