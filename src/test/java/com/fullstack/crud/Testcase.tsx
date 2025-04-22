import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import AddApplicationsGrid from "../AddApplicationsGrid";
import { RowContext } from "../../../../App";

const mockContext = {
  selectedRow: [{ id: "prod-1", productName: "Test Product" }],
  setIsAdded: jest.fn(),
  setApplicationIdentifier: jest.fn(),
  applicationIdentifier: { label: "", value: "" },
  setIsEdited: jest.fn(),
  activeRows: [],
  setChecked: jest.fn(),
  error: false,
};

const renderComponent = () =>
  render(
    <BrowserRouter>
      <RowContext.Provider value={mockContext}>
        <AddApplicationsGrid />
      </RowContext.Provider>
    </BrowserRouter>
  );

test("shows cancel dialog when cancel is clicked", async () => {
  renderComponent();

  const cancelButton = screen.getByText(/cancel/i);
  fireEvent.click(cancelButton);

  await waitFor(() => {
    expect(screen.getByText(/Confirm Cancel/i)).toBeInTheDocument();
  });

  // simulate clicking "No"
  fireEvent.click(screen.getByRole("button", { name: /No/i }));

  await waitFor(() => {
    expect(screen.queryByText(/Confirm Cancel/i)).not.toBeInTheDocument();
  });
});
