// Add the new test cases here
  test("displays 'No Data Updated' message when form is not modified (lines 486-487)", async () => {
    render(
      <Router>
        <RowContext.Provider value={mockRowContextValues}>
          <AddApplicationsGrid />
        </RowContext.Provider>
      </Router>
    );

    fireEvent.click(screen.getByText("next"));
    await waitFor(() => {
      expect(screen.getByText("noDataUpdatedMessage")).toBeInTheDocument();
    });
  });

  test("handleCancelConfirm navigates or calls handleNext based on byPassAddDupRecord (lines 583-584)", async () => {
    const mockNavigate = jest.fn();
    jest.mock("react-router-dom", () => ({
      ...jest.requireActual("react-router-dom"),
      useNavigate: () => mockNavigate,
    }));

    render(
      <Router>
        <RowContext.Provider value={{ ...mockRowContextValues, byPassAddDupRecord: true }}>
          <AddApplicationsGrid />
        </RowContext.Provider>
      </Router>
    );

    fireEvent.click(screen.getByText("Yes"));
    await waitFor(() => {
      expect(mockNavigate).not.toHaveBeenCalled(); // handleNext should be called instead
    });
  });

  test("Dialog displays duplicate countries and handles 'Show more' button (lines 604-625)", async () => {
    render(
      <Router>
        <RowContext.Provider
          value={{
            ...mockRowContextValues,
            dupcountries: ["Country1", "Country2", "Country3", "Country4", "Country5"],
          }}
        >
          <AddApplicationsGrid />
        </RowContext.Provider>
      </Router>
    );

    fireEvent.click(screen.getByText("next"));
    await waitFor(() => {
      expect(screen.getByText("Duplicate Application Found")).toBeInTheDocument();
      expect(screen.getByText("Country1")).toBeInTheDocument();
      expect(screen.getByText("Show more (1)")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Show more (1)"));
    await waitFor(() => {
      expect(screen.getByText("Country5")).toBeInTheDocument();
    });
  });
